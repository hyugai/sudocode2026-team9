#!/usr/bin/env python3
"""Build authored Vietnamese dialogue fixtures; never runs a sales agent or TTS."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
MAIN = HERE.parent
ORGANIZER = MAIN.parent / "organizer"
SOURCE_SCENARIO_PATHS = tuple(sorted((MAIN / "scenarios_complete").glob("SC-*.json")))
SOURCE_SCENARIO_MAX = max(int(path.stem.split("-")[1]) for path in SOURCE_SCENARIO_PATHS)
REGIONS = {"bac": "Bắc", "trung": "Trung", "nam": "Nam"}
PAYMENTS = {"COD": "thanh toán khi nhận hàng", "bank": "chuyển khoản", "momo": "MoMo", "zalopay": "ZaloPay"}
SCENARIO_FIELDS = ("scenario_id", "level", "persona", "hard_case", "customer_phone", "customer_name", "honorific", "notes", "calls")


def corpus_scenario_id(ordinal: int) -> str:
    """Continue numbering after the original corpus without changing source IDs."""
    return f"SC-{SOURCE_SCENARIO_MAX + ordinal:03d}"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def scenario_export(scenario):
    """Match scenarios_complete/ exactly; keep build metadata in its sidecar."""
    exported = {key: copy.deepcopy(scenario[key]) for key in SCENARIO_FIELDS}
    for call in exported["calls"].values():
        call.pop("transcript_ref", None)
    return exported


def reference_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ORGANIZER / "eval" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def money(value):
    return f"{value:,}".replace(",", ".")


def fold(text):
    return "".join(c for c in unicodedata.normalize("NFD", text.lower().replace("đ", "d")) if unicodedata.category(c) != "Mn")


def scrub(text):
    # Synthetic identifiers are needed by tools, but are not read aloud by agents.
    text = re.sub(r"\b0\d{9}\b", lambda m: "số kết thúc bằng " + m[0][-4:], text)
    text = re.sub(r"\b\d+ đường Kiểm Thử,\s*", "địa chỉ đã xác nhận tại ", text)
    return text.replace("địa chỉ địa chỉ đã xác nhận", "địa chỉ đã xác nhận").replace("thanh toán thanh toán khi nhận hàng", "thanh toán khi nhận hàng")


class Dialogue:
    def __init__(self, mock, scenario, call_id, call, customer, previous):
        self.mock = mock
        self.scenario = scenario
        self.call_id = call_id
        self.call = call
        self.customer = customer
        self.previous = previous
        self.utterances = []
        self.tools = []
        self.sources = set()
        self.pending_tools = []
        self.h = scenario["honorific"]
        # Dialogue variants depend on corpus order, independently of export numbering.
        self.i = int(scenario["scenario_id"].split("-")[-1]) - SOURCE_SCENARIO_MAX
        self.first = call_id == "call_1"
        self.family = scenario["persona"]
        self.facts = call.get("facts_established", {})
        self.args = call["success_if"].get("args_match", {})
        self.sku = self.facts.get("product_advised") or previous.get("product_advised") or self.args.get("sku")
        if self.facts.get("variant_sku"):
            self.sku = self.facts["variant_sku"]
        if not self.sku:
            self.sku = scenario["fixture"]["products"][0]["sku"]
        self.address = self.facts.get("delivery_address") or previous.get("delivery_address") or self.args.get("address")
        self.quote = None
        self.known_payment = previous.get("payment")

    def tool(self, name, **args):
        runtime = dict(args)
        if name not in ("crm.get_customer", "catalog.search", "schedule.callback", "handoff.transfer"):
            runtime["on"] = self.call["call_date"]
        if name == "order.status":
            runtime.pop("on", None)
        result = self.mock.TOOLS[name](**runtime)
        index = len(self.tools)
        self.tools.append({"name": name, "args": runtime, "result": result, "origin": "executed_reference_mock_for_authored_fixture"})
        self.pending_tools.append(index)
        return result

    def customer_says(self, text, original_index=None):
        row = {"speaker": "customer", "text": text}
        if original_index is not None:
            row["source_customer_turn_index"] = original_index
        self.utterances.append(row)

    def agent_says(self, text, *sources):
        self.sources.update(sources)
        self.utterances.append({"speaker": "agent", "text": scrub(text), "source_refs": list(sources), "tool_refs": self.pending_tools[:]})
        self.pending_tools.clear()

    def name(self, sku=None):
        p, variant = self.mock._parent(sku or self.sku)
        if variant:
            color = {"den": "đen", "trang": "trắng", "be": "be", "navy": "navy"}.get(variant["color"], variant["color"])
            return f"{p['name']}, size {variant['size']}, màu {color}"
        return p["name"]

    def current_quote(self, sku=None):
        sku = sku or self.sku
        self.tool("catalog.search", sku=sku)
        inv = self.tool("inventory.check", sku=sku)
        q = self.tool("pricing.get_quote", sku=sku, customer_phone=self.scenario["customer_phone"], address=self.address)
        self.quote = q
        availability = "hiện còn hàng" if inv["in_stock"] else "hiện hết hàng"
        restock = f"; dự kiến có lại ngày {inv['restock_expected']}" if inv.get("restock_expected") else ""
        return f"{self.name(sku)} có giá {money(q['final_price_vnd'])} đồng một sản phẩm, {availability}{restock}."

    def opening(self):
        self.tool("crm.get_customer", phone=self.scenario["customer_phone"])
        if not self.first:
            if self.family == "khach_goi_lan_3_het_kien_nhan":
                return f"Dạ {self.h}, em tiếp tục đúng yêu cầu lần trước và sẽ xử lý ngắn gọn."
            if self.family == "hai_nguoi_chung_sdt":
                return f"Dạ {self.h} {self.scenario['customer_name']}, em tiếp tục hồ sơ riêng của {self.h}, không lấy nhu cầu của người dùng chung số."
            if self.family == "khach_hoi_ngoai_tai_lieu":
                question = self.previous.get("unresolved_question", "câu hỏi chưa có nguồn xác nhận")
                return f"Dạ {self.h}, em còn lưu câu hỏi: {question} Hiện em không có thông tin xác nhận nên chưa thể trả lời chắc chắn."
            if self.family == "khach_ngoai_pham_vi_chuyen_may":
                return f"Dạ {self.h}, em còn lưu {self.name()} và việc mình cần làm rõ câu hỏi sức khỏe. Em tiếp tục đúng nội dung đó, không yêu cầu {self.h} kể lại từ đầu."
            if self.family == "khach_da_mua_doi_size":
                self.tool("order.status", order_id="OD600001")
                return f"Dạ {self.h}, em đã tìm đơn OD600001 của lần mua trước. Em ghi nhận việc đã nhận hàng theo thông tin {self.h} vừa báo, sẽ đối chiếu điều kiện đổi trước khi xử lý."
            if self.family in ("khach_so_gia", "khach_da_kenh_mau_thuan"):
                old = self.previous["price_quoted_vnd"]
                return f"Dạ {self.h}, em còn lưu mức {money(old)} đồng đã báo ở phiên trước. Em kiểm tra lại theo ngày tạo đơn hôm nay; giá lịch sử không tự động được giữ nếu ưu đãi đã hết hạn. {self.current_quote()}"
            if self.family == "khach_mua_nhieu_mon":
                basket = self.previous["basket_skus"]
                q = self.tool("pricing.quote_order", lines=[{"sku": s, "qty": 1} for s in basket], customer_phone=self.scenario["customer_phone"], address=self.address)
                return f"Dạ {self.h}, giỏ đã sửa gồm {' và '.join(self.name(s) for s in basket)}; món đã bỏ không còn trong giỏ. Tổng hàng hôm nay là {money(q['total_vnd'])} đồng."
            product = self.name()
            return f"Dạ {self.h} {self.scenario['customer_name']}, em tiếp tục phần {product} đã trao đổi. Em dùng lựa chọn đã lưu và kiểm tra lại giá, tồn kho trước khi chốt."
        if self.family == "khach_quay_lai_sau_8_thang":
            return f"Dạ {self.h}, em tra lịch sử mua trước đây để kiểm tra điều kiện thu cũ đổi mới. Bản AirPure X 2024 đã ngừng bán; em sẽ kiểm tra riêng máy mới {self.h} chọn, không dùng lại giá hay địa chỉ từ tám tháng trước."
        if self.family == "khach_mua_nhieu_mon":
            return f"Dạ {self.h}, em ghi nhận hai món vừa nêu. Em sẽ chờ {self.h} xác nhận giỏ cuối cùng rồi mới báo tổng và tạo đơn, tránh đặt nhầm khi mình còn thay đổi lựa chọn."
        if self.family == "hai_nguoi_chung_sdt":
            return f"Dạ {self.h} {self.scenario['customer_name']}, em ghi nhận đây là nhu cầu riêng của {self.h}. {self.current_quote()} Em tách thông tin này khỏi hồ sơ người dùng chung số."
        return f"Dạ {self.h}, {self.current_quote()} Em sẽ tư vấn theo sản phẩm và điều kiện hiện hành, chưa tạo đơn khi mình chưa đồng ý."

    def reply(self, text, index):
        normalized = fold(text)
        if index == 0:
            return self.opening()
        if "ban chinh sach thang 6" in normalized:
            return "Với đơn mới từ tháng 10/2026, thời hạn đổi trả thông thường là 7 ngày kể từ ngày nhận, khi hàng đủ điều kiện. Bản tháng 6 có 14 ngày chỉ để tra đơn cũ, không áp cho đơn mới này."
        if "ma thuc su da het han" in normalized or "ap lai ma" in normalized or ("het han" in normalized and "chuong trinh" in normalized):
            return f"Ưu đãi đó đã hết hạn nên em không áp lại cho đơn hôm nay. Giá hiện hành cần lấy từ hệ thống: {self.current_quote()} Em không tự cộng thêm mức giảm ngoài chương trình."
        if self.family == "khach_ngoai_pham_vi_chuyen_may" and not self.first:
            return "Câu hỏi này thuộc tư vấn y tế nên em không thể xác nhận tác dụng, độ an toàn hay thay đổi thuốc. Em có thể gửi người phụ trách sản phẩm kèm nội dung đã trao đổi; phần đánh giá y tế cần hỏi bác sĩ hoặc người có chuyên môn."
        if self.family == "khach_hoi_ngoai_tai_lieu":
            return "Hiện em không có thông tin xác nhận chi tiết đó trong tài liệu và hồ sơ sản phẩm. Em ghi nhận câu hỏi đang chờ nguồn chính thức, không suy đoán từ sản phẩm khác và chưa đánh dấu là đã giải đáp."
        if self.family in ("khach_so_gia", "khach_da_kenh_mau_thuan"):
            if self.first:
                expiry = self.facts.get("promo_expiry")
                code = self.facts.get("promo_code")
                promo = next((p for p in self.mock.PROMOS if p["promo_code"] == code), None)
                expiry = expiry or (promo["end"] if promo else "ngày cuối của chương trình")
                return f"Mức {money(self.facts['price_quoted_vnd'])} đồng gắn với {code}, kết thúc ngày {expiry}. Em ghi nhận ngân sách của {self.h}; khi mình quay lại, em phải kiểm tra chương trình tại ngày đặt, không tự giữ ưu đãi đã hết."
            old = self.previous["price_quoted_vnd"]
            return f"Em xin lỗi vì hai lần liên hệ có giá khác nhau. Mức {money(old)} đồng thuộc chương trình cũ đã hết hạn; {self.current_quote()} Em giải thích theo thời điểm, không lấy giá từ kênh này thay cho việc kiểm tra trên hệ thống."
        if self.family == "khach_da_mua_doi_size" and not self.first:
            sku = self.args["new_variant_sku"]
            inv = self.tool("inventory.check", sku=sku)
            assert inv["in_stock"], sku
            return f"{self.name(sku)} còn hàng. Với thông tin {self.h} vừa xác nhận về ngày nhận, tem hộp và chưa sử dụng, lần đổi size đầu tiên được miễn phí vận chuyển hai chiều. Em sẽ tạo yêu cầu đúng đơn cũ, không tạo đơn mua mới."
        if self.family == "khach_hoi_nhieu_khong_mua" and not self.first:
            return "Chính sách hiện hành là 7 ngày kể từ ngày nhận; hàng cần chưa sử dụng, còn tem nhãn và hộp. Đổi size lần đầu miễn phí hai chiều khi size mới còn hàng. Mốc 14 ngày và phí 20 nghìn là bản cũ, không dùng cho đơn mới tháng 10 này."
        if self.family == "khach_mua_nhieu_mon":
            if self.first:
                basket = self.facts["basket_skus"]
                q = self.tool("pricing.quote_order", lines=[{"sku": s, "qty": 1} for s in basket], customer_phone=self.scenario["customer_phone"], address=self.address)
                return f"Em cập nhật giỏ cuối gồm {' và '.join(self.name(s) for s in basket)}, mỗi món một chiếc. Tổng hàng hiện tại {money(q['total_vnd'])} đồng; món {self.name(self.facts['removed_sku'])} đã được loại khỏi lựa chọn, chưa có đơn được tạo."
            if "thanh toan" in normalized or "cod" in normalized:
                self.known_payment = self.facts.get("payment")
                return f"Em ghi nhận {PAYMENTS.get(self.known_payment, 'phương thức mình vừa chọn')}. Em sẽ xác nhận tổng một lần trước khi tạo một đơn nhiều dòng đúng giỏ đã sửa."
            return f"Em ghi nhận đúng hai món, số lượng và địa chỉ mình vừa cung cấp. Em chờ {self.h} chọn cách thanh toán rồi xác nhận tổng trước khi tạo một đơn nhiều dòng."
        if self.family == "khach_quay_lai_sau_8_thang":
            if not self.first:
                return f"{self.current_quote()} Em dùng địa chỉ mới đã xác nhận ở phiên vừa rồi, không lấy lại địa chỉ tám tháng trước. Em đã ghi nhận người nhà đồng ý; mình chỉ cần xác nhận đơn trước khi tạo."
            if "dia chi" in normalized:
                return f"Em ghi nhận địa chỉ mới {self.h} vừa cung cấp; địa chỉ cũ chỉ giữ trong lịch sử, không đưa vào đơn mới. Em chưa tạo đơn khi mình chưa quyết định."
            return f"Em đã đối chiếu lịch sử sở hữu máy cũ để xét thu cũ đổi mới. {self.current_quote()} Địa chỉ từ tám tháng trước cần xác nhận lại trước khi dùng cho đơn mới."
        if "14 ngay" in normalized:
            return "Đơn mới hiện nay có thời hạn đổi trả thông thường 7 ngày kể từ ngày nhận, không phải 14 ngày. Em sẽ đối chiếu ngày tạo đơn nếu mình đang hỏi một đơn cũ."
        if "ngan sach" in normalized:
            return f"Em ghi nhận ngân sách {money(self.facts.get('budget_vnd', self.previous.get('budget_vnd', 0)))} đồng và mức giá vừa kiểm tra. Em không thay mẫu hay vượt ngân sách khi chưa hỏi ý kiến {self.h}."
        return f"Dạ {self.h}, em đã ghi nhận nội dung vừa xác nhận và giữ đúng lựa chọn của mình. Giá và tồn kho vẫn cần kiểm tra tại ngày đặt; em chưa tự tạo đơn hay thêm lịch gọi ngoài yêu cầu của {self.h}."

    def qa(self):
        # Four useful exchanges, before the customer's closing instruction. Busy callers
        # and medical handoffs stay brief; simulator outlines stay below 12 customer turns.
        if self.family == "khach_goi_lan_3_het_kien_nhan" and not self.first:
            return
        if self.family == "khach_ngoai_pham_vi_chuyen_may" and not self.first:
            return
        if self.scenario["fixture"]["new_customer"] and self.call_id == "call_3":
            return
        if not self.first:
            if self.family in ("khach_hoi_ngoai_tai_lieu", "khach_da_mua_doi_size"):
                return
            self.customer_says(f"Khi giao hàng, ngày nghỉ có tính vào thời gian giao không? {self.h.capitalize()} cần biết đây là thời gian dự kiến hay một giờ giao được bảo đảm.")
            self.agent_says("Thời gian giao được tính theo ngày làm việc, không gồm Chủ nhật, ngày lễ và lịch nghỉ nội bộ. Giờ đặt sau 16 giờ cũng ảnh hưởng mốc xử lý. Em chỉ báo dự kiến theo đơn và khu vực, không bảo đảm một giờ giao cụ thể khi chưa có xác nhận từ vận chuyển.", "policy/chinh-sach-van-chuyen-thanh-toan.md#VC-01")
            self.customer_says(f"Nếu cần tra tiến độ sau này, {self.h} xem ở đâu? Em đừng coi vừa tạo đơn là đã giao xong nhé.")
            self.agent_says("Mã đơn dùng để tra trạng thái trên hệ thống hoặc liên hệ Zalo OA. Mã vận đơn được gửi khi hàng bàn giao cho đơn vị vận chuyển. Tạo đơn, bàn giao và đã nhận hàng là ba trạng thái khác nhau; em chỉ xác nhận trạng thái có nguồn, không tự coi đơn đã giao.", "policy/chinh-sach-van-chuyen-thanh-toan.md#VC-06")
            return
        old = self.call["call_date"] < "2026-10-01"
        p, _ = self.mock._parent(self.sku)
        h = self.h
        n = self.i % 3
        questions = [
            f"{h.capitalize()} muốn biết giá em báo là giá một sản phẩm hay đã gồm nhiều món; nếu quay lại hôm khác có cần kiểm tra lại không?",
            f"Em tách giúp {h} giá từng món với tổng giỏ nhé. Giá hôm nay có được tự giữ cho lần liên hệ sau không?",
            f"Mình chưa chốt ngay thì giá này tính tại ngày nào? {h.capitalize()} không muốn lần sau hiểu nhầm là shop đã giữ giá.",
        ]
        self.customer_says(questions[n])
        self.agent_says("Giá một sản phẩm là giá sau ưu đãi được hệ thống kiểm tra ở ngày tư vấn; tổng giỏ là cộng các đơn vị mình chọn. Khi quay lại em kiểm tra lại theo ngày tạo đơn. Chưa có mã đơn thì giá cũ là lịch sử, không phải cam kết giữ giá qua ngày hết hạn.", "policy/dieu-khoan-khuyen-mai.md#KM-01")
        self.customer_says([
            f"Nếu hàng bị lỗi thì bảo hành khác đổi trả ở điểm nào? {h.capitalize()} muốn biết điều kiện để còn giữ giấy tờ.",
            f"Ngoài giá, {h} cần rõ bảo hành có bao gồm rơi vỡ hay tự làm hỏng không, để tránh hiểu sai lúc mua.",
            f"Em nói riêng phần bảo hành giúp {h}; đừng gộp mọi lỗi sử dụng vào lỗi của hãng nhé.",
        ][n])
        warranty = p.get("attributes", {}).get("warranty_months")
        if warranty:
            answer = f"Catalog của mẫu này ghi bảo hành {warranty} tháng. Phạm vi là lỗi kỹ thuật do nhà sản xuất; hao mòn tự nhiên, rơi vỡ, vào nước, dùng sai điện áp hoặc tự tháo máy không thuộc phạm vi đó. Mình giữ hóa đơn hoặc mã đơn để đối chiếu. Đổi trả là quy trình khác và phải xét thời hạn riêng."
        else:
            answer = "Em chưa có thời hạn bảo hành riêng của mẫu này trong catalog để khẳng định thêm. Với giày và áo khoác, chính sách áp dụng đổi trả, không phải bảo hành như đồ điện. Khi có vấn đề, mình giữ hóa đơn, tem nhãn và nêu rõ tình trạng để shop đối chiếu đúng điều kiện."
        self.agent_says(answer, "catalog/products.json", "policy/chinh-sach-bao-hanh.md#BH-01", "policy/chinh-sach-bao-hanh.md#BH-02")
        self.customer_says([
            f"Còn thời hạn đổi trả của đơn đặt hôm nay thì tính từ lúc nào? {h.capitalize()} cần chuẩn bị tem hộp thế nào?",
            f"Nếu đặt hôm nay mà nhận về không phù hợp, {h} có được đổi vô điều kiện không? Em nói giúp mốc thời gian và tình trạng hàng.",
            f"{h.capitalize()} sẽ giữ hộp. Em nhắc thời hạn và điều kiện đổi trả của đơn mới giúp, để không lấy nhầm bài chính sách cũ.",
        ][n])
        if old:
            answer = "Đơn tạo trước ngày 01/10/2026 áp dụng bản chính sách tháng 6: thời hạn đổi trả 14 ngày kể từ khi nhận; cần còn tem nhãn, hộp và hóa đơn. Phí đổi size theo bản này là 20.000 đồng một lần và khách chịu phí gửi trả. Em đối chiếu ngày tạo đơn, không dùng lẫn phiên bản chính sách."
            refs = ("policy/chinh-sach-doi-tra-v2026-06-HET-HIEU-LUC.md", "policy/changelog.md#CL-01")
        else:
            answer = "Thời hạn thông thường là 7 ngày kể từ ngày nhận, với hàng còn tem nhãn, hộp, chưa sử dụng và có hóa đơn hoặc mã đơn. Gia dụng, mẹ và bé có lỗi kỹ thuật nhà sản xuất được xét đổi mới trong 30 ngày khi đủ xác nhận. Hàng vệ sinh đã bóc seal và hư do người dùng có điều kiện loại trừ, nên không phải mọi lý do đều đổi được."
            refs = ("policy/chinh-sach-doi-tra.md#DT-01", "policy/chinh-sach-doi-tra.md#DT-02", "policy/chinh-sach-doi-tra.md#DT-06")
        self.agent_says(answer, *refs)
        topic = self.i % 3
        if topic == 0 and p["category"].startswith("thoi-trang"):
            question = f"Size vừa chọn có được bảo đảm chắc chắn vừa không? {h.capitalize()} cần giữ hàng thế nào nếu phải đổi size?"
            answer = "Bảng size là hướng dẫn tham khảo, em không thể bảo đảm vừa tuyệt đối khi mình chưa thử. Mình giữ nguyên tem nhãn, hộp, chưa giặt và chưa làm mòn sản phẩm; nếu cần đổi, shop kiểm tra điều kiện và tồn kho đúng biến thể mới. Em không tự đổi size đã chọn khi chưa có yêu cầu."
            refs = ("policy/spec-thoi-trang-me-be.md#SP-SN-01" if "/giay" in p["category"] else "policy/spec-thoi-trang-me-be.md#SP-JK-01", "policy/chinh-sach-doi-tra.md#DT-02")
        elif topic == 0:
            question = f"Nếu cần bảo hành, {h} gửi qua shop thế nào? Có được hứa xong ngay trong ngày không?"
            answer = "Mình có thể mang đến trung tâm bảo hành hãng hoặc gửi qua shop để hỗ trợ chuyển đến hãng; phí vận chuyển chiều đi do khách chịu. Thời gian xử lý theo chính sách là 7–15 ngày làm việc. Em không hứa xong ngay trong ngày, vì cần kiểm tra và xác nhận tình trạng thực tế trước."
            refs = ("policy/chinh-sach-bao-hanh.md#BH-03",)
        elif topic == 1:
            question = f"Khi đổi kênh liên hệ, em có nhớ đúng nhu cầu của {h} không? {h.capitalize()} cũng muốn biết em là người thật hay trợ lý ảo."
            answer = "Em là trợ lý AI của shop. Em dùng định danh kênh và thông tin mình xác nhận để tìm đúng hồ sơ, rồi chỉ nhắc phần liên quan của lần trước. Nếu có hai người chung số, em cần phân biệt đúng người trước khi dùng ký ức. Em không tự lấy thông tin của một người ghép sang người khác."
            refs = ("policy/playbook-telesale.md#PB-01", "policy/playbook-telesale.md#PB-07", "schemas/tools.schema.json")
        else:
            question = f"{h.capitalize()} chưa muốn quyết vội. Em ghi nhận nhu cầu được, nhưng đừng tự đặt hàng hoặc gọi dồn khi chưa hẹn nhé."
            answer = "Dạ, em ghi nhận nhu cầu và phần mình còn cân nhắc, chưa coi đó là đồng ý mua. Em chỉ tạo đơn khi mình xác nhận, và chỉ đặt lịch gọi lại khi có thời điểm được đồng ý. Với khách nhiều lần chưa mua, shop không tiếp tục gọi chủ động sau ba phiên nếu mình không hẹn."
            refs = ("policy/playbook-telesale.md#PB-03", "policy/playbook-telesale.md#PB-11")
        self.customer_says(question)
        self.agent_says(answer, *refs)

    def finish(self):
        si = self.call["success_if"]
        action = si.get("tool_called")
        if action == "order.create":
            basket = si.get("also_ordered")
            args = copy.deepcopy(self.args)
            if basket:
                q = self.tool("pricing.quote_order", lines=[{"sku": s, "qty": 1} for s in basket], customer_phone=self.scenario["customer_phone"], address=args["address"])
                args = {k: v for k, v in args.items() if k not in ("sku", "qty", "price_vnd")}
                args["lines"] = [{"sku": u["sku"], "qty": 1, "price_vnd": u["final_price_vnd"]} for u in q["units"]]
                summary = "; ".join(f"{self.name(u['sku'])}: {money(u['final_price_vnd'])} đồng" for u in q["units"])
                total = q["total_vnd"]
            else:
                self.current_quote(args["sku"])
                total = args["qty"] * args["price_vnd"]
                summary = f"{args['qty']} sản phẩm {self.name(args['sku'])}, đơn giá {money(args['price_vnd'])} đồng"
            eta = self.mock._eta(self.call["call_date"], args["address"])
            self.agent_says(f"Em xác nhận một lần: {summary}; tổng hàng {money(total)} đồng, {PAYMENTS[args['payment']]}, giao theo địa chỉ {args['address']}. Dự kiến giao ngày {eta}, có tính ngày nghỉ; đây là dự kiến. Mình xác nhận để em tạo đơn này nhé?", "policy/playbook-telesale.md#PB-09", "policy/chinh-sach-van-chuyen-thanh-toan.md#VC-01")
            self.customer_says(f"Đúng rồi, {self.h} xác nhận đúng sản phẩm, số lượng, tổng tiền, địa chỉ và cách thanh toán vừa nhắc. Em tạo đơn giúp nhé.")
            result = self.tool(action, **args)
            assert not result.get("error"), (self.scenario["scenario_id"], self.call_id, result)
            message = f"Đơn {result['order_id']} đã được tạo, tổng hàng {money(result['total_vnd'])} đồng. Dự kiến giao ngày {result['estimated_delivery']}."
            if result["needs_confirmation_call"]:
                message += " Đơn COD này cần cuộc gọi xác nhận trước khi giao."
            self.agent_says(message, "policy/chinh-sach-van-chuyen-thanh-toan.md#VC-05")
        elif action == "schedule.callback":
            result = self.tool(action, **self.args)
            changed = " Lịch được dời theo ngày nghỉ hoặc giờ phục vụ." if result.get("moved_from") else ""
            self.agent_says(f"Em đã ghi lịch liên hệ lại lúc {result['callback_at'].replace('T', ' ')}.{changed} Em lưu phần đang cân nhắc để lần tới mình tiếp tục, chưa tạo đơn.", "policy/playbook-telesale.md#PB-03")
        elif action == "order.update":
            result = self.tool(action, **self.args)
            assert not result.get("error"), result
            self.agent_says(f"Em đã gửi yêu cầu đổi size cho đơn {result['order_id']}; trạng thái chờ sắp lịch lấy hàng. Phí đổi lần này là {money(result['fee_vnd'])} đồng. Shop dự kiến bố trí lấy trong 1–2 ngày làm việc; đây chưa phải xác nhận đã lấy hoặc đã giao hàng đổi.", "policy/chinh-sach-doi-tra.md#DT-03", "policy/chinh-sach-doi-tra.md#DT-07")
        elif action == "handoff.transfer":
            brief = {"customer_phone": self.scenario["customer_phone"], "customer_name": self.scenario["customer_name"], "escalation_reason": "Câu hỏi y tế vượt phạm vi tư vấn bán hàng", "conversation_summary": self.call["customer_goal"], "product_advised": self.sku, "price_quoted_vnd": self.previous["price_quoted_vnd"], "open_questions": [self.facts["medical_question"]], "next_action": "Nhân viên phụ trách tiếp nhận; khuyến nghị hỏi bác sĩ về y tế", "generated_at": self.call["call_date"] + "T10:00:00+07:00"}
            result = self.tool(action, brief=brief)
            assert not result.get("error"), result
            self.agent_says(f"Em đã gửi yêu cầu {result['ticket_id']} đến người phụ trách, kèm sản phẩm, giá đã trao đổi và câu hỏi của {self.h}. Yêu cầu đang trong hàng chờ; em chưa thể xác nhận thời điểm có người nhận máy và không đưa ra kết luận y tế.", "policy/playbook-telesale.md#PB-06")
        elif self.family == "khach_hoi_ngoai_tai_lieu":
            self.agent_says("Hiện em không có thông tin xác nhận câu hỏi đó. Em giữ trạng thái chờ nguồn, chưa tạo đơn và không chuyển máy ngoài yêu cầu của mình.", "policy/playbook-telesale.md#PB-05")
        elif self.family == "khach_hoi_nhieu_khong_mua" and not self.first:
            self.agent_says("Dạ, em ghi nhận mình chưa mua. Để tránh nhầm bản cũ, em nhắc gọn: đơn mới có thời hạn thông thường 7 ngày, đổi size lần đầu miễn phí khi đủ điều kiện. Em không tạo đơn và không đặt lịch gọi lại khi mình chưa hẹn.", "policy/chinh-sach-doi-tra.md#DT-01", "policy/chinh-sach-doi-tra.md#DT-03")
        else:
            basket = self.facts.get("basket_skus")
            recap = f"Giỏ cuối là {' và '.join(self.name(s) for s in basket)}. " if basket else ""
            self.agent_says(f"Dạ {self.h}, {recap}em ghi nhận mình chưa đặt hàng và giữ nội dung vừa trao đổi để tiếp tục đúng nhu cầu. Em chưa tạo đơn hay tự thêm lịch gọi lại.", "policy/playbook-telesale.md#PB-03")

    def build(self):
        original = self.call["customer_turns"][:]
        insert_after = 1 if self.family in ("khach_mua_nhieu_mon", "khach_quay_lai_sau_8_thang") else 0
        for index, text in enumerate(original):
            self.customer_says(text, index)
            if index == len(original) - 1:
                self.finish()
            else:
                self.agent_says(self.reply(text, index), "schemas/tools.schema.json", "catalog/products.json")
                if "ban chinh sach thang 6" in fold(text):
                    self.sources.add("policy/changelog.md#CL-01")
                if index == insert_after:
                    self.qa()
        assert not self.pending_tools
        return self


def extra_scenarios(mock):
    names = ["Minh Anh", "Quốc Bảo", "Hà Chi", "Đức Duy", "Ngọc Hà", "Gia Huy", "Khánh Linh", "Tuấn Kiệt", "Thanh Mai", "Nhật Minh", "Yến Nhi", "Hoàng Phúc", "Bảo Quyên", "Minh Quân", "Phương Thảo", "Quang Trung", "Tường Vy", "Hải Đăng", "Diệu An", "Bình Minh"]
    names += ["Anh Thư", "Trọng Nghĩa", "Ngọc Trâm", "Hoài Nam", "Thiên Kim", "Văn Sơn", "Mỹ Duyên", "Đình Phong", "Thanh Hằng", "Quốc Khánh", "Bảo Châu", "Hữu Lộc", "Tú Anh", "Thanh Tùng", "Ngọc Yến", "Thành Đạt"]
    configurations = [[{"sku": "SKU-AP-PRO", "qty": 2}], [{"sku": "SKU-SS-AX40", "qty": 1}, {"sku": "SKU-AP-X", "qty": 1}], [{"sku": "SKU-AP-PRO", "qty": 3}], [{"sku": "SKU-AP-Y", "qty": 1}, {"sku": "SKU-AP-MINI", "qty": 1}], [{"sku": "SKU-AP-X", "qty": 2}]]
    for j, name in enumerate(names):
        sid = corpus_scenario_id(len(SOURCE_SCENARIO_PATHS) + j + 1)
        phone = f"090900{j+1:04d}"
        region = list(REGIONS)[j % 3]
        city = {"bac": "Hà Nội", "trung": "Đà Nẵng", "nam": "TP. Hồ Chí Minh"}[region]
        address = f"{200+j} đường Kiểm Thử, {city}"
        customer = {"customer_id": f"M2-C{j+1:03d}", "name": name, "honorific": "chị" if j % 2 == 0 else "anh", "phone": phone, "region": region, "fb_id": f"m2.fb.{j+1:03d}", "zalo_id": f"m2.zalo.{j+1:03d}", "orders": [], "synthetic": True, "source": "team-authored additional test identity"}
        lines = copy.deepcopy(configurations[j % 5])
        quote = mock.pricing_quote_order(lines, on="2026-10-22", customer_phone=phone, address=address)
        payment = "bank" if quote["total_vnd"] > 10000000 else "COD"
        chat = "chat_fanpage" if j % 2 == 0 else "zalo_oa"
        h = customer["honorific"]
        basket_text = "; ".join(f"{line['qty']} {mock._parent(line['sku'])[0]['name']}" for line in lines)
        s = {"scenario_id": sid, "level": "M2", "persona": "khach_mua_nhieu_mon", "hard_case": "hai_may_cung_gia" if j % 5 in (0, 4) else "gio_nhieu_may_chi_mot_lan_giam", "customer_phone": phone, "customer_name": name, "honorific": h, "notes": "Khách tổng hợp mới, không phải bản đổi tên của khách BTC. Một phiên chat và hai phiên hotline liên kết qua SĐT khách tự cung cấp; chỉ chốt ở phiên thứ ba. Báo giá theo mock 11/2026; AIR-2ND-50 chỉ một máy, cùng giá chọn máy sau; đơn trên 10 triệu dùng chuyển khoản. Chỉ nạp fixture khách trong môi trường test; không nạp lời agent mẫu vào agent được đánh giá.", "fixture": {"customer_id": customer["customer_id"], "customer": customer, "products": [mock._parent(li["sku"])[0] for li in lines], "new_customer": True, "basket_lines": lines}, "calls": {}}
        for call_no, date in [(1, "2026-10-22"), (2, "2026-10-24"), (3, "2026-10-27")]:
            channel = chat if call_no == 1 else "hotline"
            identity = customer["fb_id" if chat == "chat_fanpage" else "zalo_id"] if call_no == 1 else phone
            current = mock.pricing_quote_order(lines, on=date, customer_phone=phone, address=address)
            turns = [f"Tôi là {name}, số điện thoại {phone}. {h.capitalize()} cần {basket_text}, giao tại {address}.", "Nếu có hai máy bằng giá thì có phải cả hai đều được giảm một nửa không? Em tính từng máy giúp, đừng gộp một giá chung.", "Nếu mua ba máy thì được giảm thêm cho máy thứ ba không? Đợt này chị chỉ lấy đúng số lượng vừa nêu.".replace("chị", h), f"Tổng hàng em tính là {money(current['total_vnd'])} đồng. {h.capitalize()} cần trao đổi người nhà, chưa đặt và không hẹn gọi chủ động."] if call_no == 1 else [f"{h.capitalize()} {name} đây, số {phone}, đã nhắn {'Fanpage' if chat == 'chat_fanpage' else 'Zalo OA'} về giỏ nhiều máy. Giữ đúng số lượng hôm trước nhé.", "Em nhắc lại từng máy được hưởng chương trình nào và tổng hôm nay; đừng cộng hai ưu đãi độc quyền trên cùng một máy.", f"{h.capitalize()} đồng ý tổng {money(current['total_vnd'])} đồng, {PAYMENTS[payment]}, địa chỉ giữ như đã nhắn. Em đọc lại đơn trước khi tạo nhé."]
            if call_no == 2:
                turns[-1] = f"Tổng {money(current['total_vnd'])} đồng thì đúng, nhưng {h} vẫn cần thống nhất với người nhà. Hôm nay chưa đặt, em chỉ lưu giỏ, đừng tự tạo đơn hoặc hẹn gọi lại."
            elif call_no == 3:
                turns[0] = f"{h.capitalize()} {name} đây, số {phone}. Người nhà đã đồng ý giỏ trao đổi ở hai phiên trước. Giữ đúng mẫu và số lượng, kiểm tra giá hôm nay rồi chốt giúp nhé."
            facts = {"basket_lines": lines, "delivery_address": address, "basket_skus": [li["sku"] for li in lines], "quantity_by_sku": {li["sku"]: li["qty"] for li in lines}}
            args = {"customer_phone": phone, "sku": current["units"][0]["sku"], "qty": 1, "price_vnd": current["units"][0]["final_price_vnd"], "payment": payment, "address": address}
            si = {"tool_called": None, "must_not_call_tools": ["order.create", "schedule.callback"], "must_say_any": [money(current["total_vnd"])]} if call_no < 3 else {"tool_called": "order.create", "args_match": args, "also_ordered": sorted({u["sku"] for u in current["units"]}), "total_match_vnd": current["total_vnd"]}
            s["calls"][f"call_{call_no}"] = {"channel": channel, "channel_identity": identity, "call_date": date, "input_mode": "clean", "customer_goal": "Hiểu giá từng máy và giới hạn ưu đãi" if call_no == 1 else "Giữ giỏ trong lúc chờ người nhà, chưa đặt" if call_no == 2 else "Chốt một đơn nhiều dòng đúng giá từng máy", "customer_turns": turns, "facts_established": facts, "expected_outcome": "tu_choi" if call_no < 3 else "chot_don", "success_if": si, "ground_truth_facts": {"total_vnd": current["total_vnd"], "discounted_second_item_count": sum(any(a["promo_code"] == "AIR-2ND-50" for a in u["applied_promos"]) for u in current["units"])}}
            if call_no > 1:
                s["calls"][f"call_{call_no}"].update({"days_later": 2 if call_no == 2 else 3, "must_carry_over": ["basket_lines", "delivery_address"], "must_not_ask": ["basket_lines", "delivery_address"]})
        yield s, customer


class BasketDialogue(Dialogue):
    """Additional customers exercise quantities and equal-price units explicitly."""
    def basket_quote(self):
        for line in self.scenario["fixture"]["basket_lines"]:
            self.tool("inventory.check", sku=line["sku"])
        return self.tool("pricing.quote_order", lines=self.scenario["fixture"]["basket_lines"], customer_phone=self.scenario["customer_phone"], address=self.address)

    def quote_text(self, quote):
        units = []
        for i, u in enumerate(quote["units"], 1):
            codes = ", ".join(p["promo_code"] for p in u["applied_promos"] if p["type"] not in ("freeship", "freecod")) or "không có giảm giá riêng"
            units.append(f"Máy {i}, {self.name(u['sku'])}: {money(u['final_price_vnd'])} đồng, {codes}")
        return "; ".join(units) + f". Tổng hàng {money(quote['total_vnd'])} đồng."

    def reply(self, text, index):
        if index == 0:
            self.tool("crm.get_customer", phone=self.scenario["customer_phone"])
            intro = "Em đã tiếp nối giỏ từ chat, không hỏi lại số lượng hay địa chỉ." if not self.first else "Em ghi nhận đúng giỏ và địa chỉ vừa cung cấp, chưa tạo đơn."
            return intro + " " + self.quote_text(self.basket_quote())
        explanation = "AIR-2ND-50 chỉ giảm cho một máy lọc không khí có giá niêm yết thấp nhất trong đơn; nếu cùng giá thì chọn máy đứng sau. Dù mua ba máy, toàn đơn vẫn chỉ có một máy nhận giảm 50%, không phải mỗi cặp được giảm một lần. Mỗi máy chỉ nhận một ưu đãi không cộng dồn; các máy còn lại có thể nhận ưu đãi phù hợp riêng."
        return explanation + (" " + self.quote_text(self.basket_quote()) if not self.first else "")

    def finish(self):
        q = self.basket_quote()
        if self.call["success_if"]["tool_called"] is None:
            self.agent_says(f"Tổng hàng hiện tại là {money(q['total_vnd'])} đồng cho đúng giỏ vừa tính. Em ghi nhận mình còn trao đổi người nhà, chưa có đơn và không tự đặt lịch gọi lại.", "eval/mock_tools.py#pricing_quote_order", "policy/dieu-khoan-khuyen-mai.md#KM-03")
            return
        args = {k: v for k, v in self.args.items() if k not in ("sku", "qty", "price_vnd")}
        args["lines"] = [{"sku": u["sku"], "qty": 1, "price_vnd": u["final_price_vnd"]} for u in q["units"]]
        cod = "Tổng trên 10 triệu nên đơn này không dùng COD; mình đã chọn chuyển khoản. " if q["total_vnd"] > 10000000 else ""
        self.agent_says(cod + self.quote_text(q) + f" Em tạo một đơn nhiều dòng, {PAYMENTS[args['payment']]}, theo địa chỉ {args['address']}. Dự kiến giao ngày {self.mock._eta(self.call['call_date'], args['address'])}, có tính ngày nghỉ. Mình xác nhận đúng giỏ này nhé?", "eval/mock_tools.py#pricing_quote_order", "policy/quy-trinh-cod-hoan-hang.md#QT-01", "policy/playbook-telesale.md#PB-09")
        self.customer_says(f"Đúng, {self.h} xác nhận đúng từng máy, tổng tiền và cách thanh toán. Em tạo một đơn, không tự thêm số lượng.")
        res = self.tool("order.create", **args)
        assert not res.get("error"), res
        confirmation = " Đơn COD này cần cuộc gọi xác nhận trước giao." if res["needs_confirmation_call"] else ""
        self.agent_says(f"Đã tạo đơn {res['order_id']}, tổng hàng {money(res['total_vnd'])} đồng; dự kiến giao {res['estimated_delivery']}.{confirmation}", "schemas/tools.schema.json#order.create")


def catalog_index(mock):
    rows = []
    for p in mock.PRODUCTS:
        for v in p["variants"] or [None]:
            rows.append({"sku": v["variant_sku"] if v else p["sku"], "parent_sku": p["sku"], "name": p["name"], "category": p["category"].split("/")[0], "variant": v, "list_price_vnd": p["list_price_vnd"] + (v["price_delta_vnd"] if v else 0), "discontinued": bool(p.get("attributes", {}).get("discontinued")), "source": "catalog/products.json", "policy_sources": ["policy/dieu-khoan-khuyen-mai.md", "policy/chinh-sach-doi-tra.md", "policy/chinh-sach-van-chuyen-thanh-toan.md"]})
    return rows


def source_scenarios():
    for ordinal, path in enumerate(SOURCE_SCENARIO_PATHS, start=1):
        s = read(path)
        pre = read(MAIN / "scenarios_prefilled" / path.name)
        ctx = pre["generation_context"]
        source_id = s["scenario_id"]
        s["scenario_id"] = corpus_scenario_id(ordinal)
        s["level"] = "M2"
        s["source_scenario_id"] = source_id
        s["notes"] = s["notes"].replace("Gọi order.create một lần cho mỗi SKU;", "Có thể tạo một đơn nhiều dòng bằng order.create(lines=...);")
        s["notes"] += " Bản mở rộng có đối thoại mẫu hai người nói; đây là dữ liệu tổng hợp có đáp án, không phải trace agent thực tế. Reset state giữa scenario, giữ state giữa call."
        s["fixture"] = {"customer_id": ctx["customer"]["customer_id"], "customer": ctx["customer"], "products": ctx["products"], "source_complete_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "new_customer": False}
        yield s, ctx["customer"]


def build() -> None:
    mock = reference_module("btc_fixture_tools", "mock_tools.py")
    original_crm = copy.deepcopy(mock.CRM)
    customers = {}
    manifest = []
    recording_plan = []
    scenario_metadata = {}
    coverage = {"origin": "authored_synthetic_reference_dialogues", "actual_agent_runs": False, "actual_audio_generated": False, "scenarios": [], "counts": {}}
    voice_index = 0
    total_utterances = 0
    sources = {}
    source_paths = [ORGANIZER / "SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì.pdf"] + sorted((ORGANIZER / "schemas").glob("*")) + sorted((ORGANIZER / "policy").glob("*")) + sorted((ORGANIZER / "catalog").glob("*.json")) + [ORGANIZER / "eval/mock_tools.py", ORGANIZER / "eval/reference_eval.py"]
    for p in source_paths:
        sources[str(p.relative_to(ORGANIZER))] = hashlib.sha256(p.read_bytes()).hexdigest()
    for scenario, customer in [*source_scenarios(), *extra_scenarios(mock)]:
        cid = customer["customer_id"]
        customers[cid] = customer
        mock.CRM = copy.deepcopy(original_crm)
        mock._ORDERS.clear()
        mock._ONCE_USED.clear()
        mock._TICKETS.clear()
        mock._CALLBACKS.clear()
        previous = {}
        memory = {}
        scripts = [f"# {scenario['scenario_id']} — {scenario['customer_name']}", "", "> Hội thoại tổng hợp có lời khách và lời agent mẫu. Không phải kết quả chạy agent. Chưa có audio hai người nói.", ""]
        scenario_coverage = {"scenario_id": scenario["scenario_id"], "customer_id": cid, "persona": scenario["persona"], "hard_case": scenario["hard_case"], "call_ids": [], "channels": []}
        for call_id, call in scenario["calls"].items():
            # Earlier scripted deliveries in the source are customer assertions, not fake
            # backend status transitions. The reference mock deliberately remains unchanged.
            cls = BasketDialogue if scenario["fixture"]["new_customer"] else Dialogue
            d = cls(mock, scenario, call_id, call, customer, previous).build()
            tid = f"{scenario['scenario_id']}-{call_id}"
            customer_turns = [u["text"] for u in d.utterances if u["speaker"] == "customer"]
            # Expanded outline stays deterministic for the BTC evaluator / simulator.
            original_asr = call.pop("customer_turns_asr", None)
            call["customer_turns"] = customer_turns
            if original_asr:
                by_original = {i: t for i, t in enumerate(original_asr)}
                call["customer_turns_asr"] = [by_original.get(u.get("source_customer_turn_index"), fold(u["text"])) for u in d.utterances if u["speaker"] == "customer"]
            call["transcript_ref"] = f"../conversations/{tid}.json"
            for key, value in call["facts_established"].items():
                old = memory.get(key)
                memory[key] = {"value": value, "source_session": old["source_session"] if old and old["value"] == value else tid, "last_confirmed_session": tid, "valid_from": old["valid_from"] if old and old["value"] == value else call["call_date"], "supersedes_session": old["source_session"] if old and old["value"] != value else None}
            previous.update(call["facts_established"])
            voice = call["channel"] == "hotline"
            region = list(REGIONS)[voice_index % 3] if voice else customer["region"]
            noisy = voice and voice_index % 5 == 0
            words = sum(len(u["text"].split()) for u in d.utterances)
            if voice:
                recording_plan.append({"transcript_id": tid, "conversation_ref": f"conversations/{tid}.json", "status": "pending_recording", "agent_voice_region": region, "customer_voice_region": region, "different_speakers_required": True, "spoken_turns": len(d.utterances), "whitespace_word_count": words, "estimated_seconds_at_150_words_per_minute": round(words / 2.5, 1), "duration_is_estimate": True, "noise_required": noisy, "noise_type": ["street", "wind", "weak_phone_signal"][(voice_index // 5) % 3] if noisy else None, "save_clean_master": True, "audio_path": None, "actual_duration_seconds": None, "segments_path": None, "segment_timestamps": "derive from actual recording; never estimate as diarization ground truth"})
                voice_index += 1
            transcript = {"transcript_id": tid, "scenario_id": scenario["scenario_id"], "source_scenario_id": scenario.get("source_scenario_id"), "customer_id": cid, "call": call_id, "channel": call["channel"], "channel_identity": call["channel_identity"], "call_date": call["call_date"], "language": "vi", "origin": "authored_synthetic_reference_dialogue", "is_actual_agent_trace": False, "audio_status": "pending_recording" if voice else "text_chat", "voice_region_target": region if voice else None, "noise_target": noisy, "utterances": d.utterances, "private_annotations": {"persona": scenario["persona"], "customer_goal": call["customer_goal"], "expected_outcome": call["expected_outcome"], "facts_established": call["facts_established"], "sentiment_target": "mất kiên nhẫn" if scenario["persona"] == "khach_goi_lan_3_het_kien_nhan" and call_id == "call_3" else "băn khoăn" if scenario["persona"] in ("khach_so_gia", "khach_da_kenh_mau_thuan", "khach_ngoai_pham_vi_chuyen_may") else "trung tính", "objection": call["facts_established"].get("blocker", previous.get("blocker")), "fact_provenance_after_call": copy.deepcopy(memory), "memory_expectation": call.get("memory_expectation"), "memory_rules": {"price_and_stock": "revalidate with tools every session; historical quote remains episodic", "address_ttl_days": 180, "intent_ttl_days": 30, "shared_phone": "resolve customer_id; never merge profiles solely by phone"}, "source_refs": sorted(d.sources), "reference_tool_executions": d.tools, "review_status": "automated_fixture_checks; human_semantic_review_pending"}}
            write(HERE / "conversations" / f"{tid}.json", transcript)
            scripts += [f"## {call_id} · {call['call_date']} · {call['channel']}", ""]
            for u in d.utterances:
                scripts += [f"**{'Khách' if u['speaker'] == 'customer' else 'Agent'}:** {u['text']}", ""]
            manifest.append({"transcript_id": tid, "scenario_id": scenario["scenario_id"], "call": call_id, "customer_id": cid, "channel": call["channel"], "conversation_path": f"conversations/{tid}.json", "conversation_sha256": hashlib.sha256((HERE / "conversations" / f"{tid}.json").read_bytes()).hexdigest(), "scenario_path": f"scenarios_complete/{scenario['scenario_id']}.json", "script_path": f"scripts/{scenario['scenario_id']}.md", "customer_turns": len(customer_turns), "agent_turns": sum(u["speaker"] == "agent" for u in d.utterances), "word_count": words, "origin": "authored_synthetic_reference_dialogue", "actual_agent_trace": False, "audio_path": None})
            scenario_coverage["call_ids"].append(tid)
            scenario_coverage["channels"].append(call["channel"])
            total_utterances += len(d.utterances)
        scenario_metadata[scenario["scenario_id"]] = {
            "source_scenario_id": scenario.get("source_scenario_id"),
            "source_scenario_path": f"../scenarios_complete/{scenario['source_scenario_id']}.json" if scenario.get("source_scenario_id") else None,
            "fixture": scenario["fixture"],
            "transcript_refs": {key: value["transcript_ref"] for key, value in scenario["calls"].items()},
        }
        write(HERE / "scenarios_complete" / f"{scenario['scenario_id']}.json", scenario_export(scenario))
        (HERE / "scripts").mkdir(exist_ok=True)
        (HERE / "scripts" / f"{scenario['scenario_id']}.md").write_text("\n".join(scripts), encoding="utf-8")
        coverage["scenarios"].append(scenario_coverage)
    write(HERE / "scenario_metadata.json", scenario_metadata)
    write(HERE / "customers.json", {"description": "BTC synthetic customer identities plus 36 new team-authored synthetic identities. These are private test fixtures, not permission to contact anyone.", "customers": sorted(customers.values(), key=lambda c: c["customer_id"])})
    sku_rows = catalog_index(mock)
    write(HERE / "catalog_skus.json", {"counting_rule": "Distinct leaf SKUs: variants replace their parent, so parents and variants are not double-counted. Stock varies with call date; discontinued rows are excluded from the active count. No products were invented.", "parent_products": len(mock.PRODUCTS), "leaf_skus": len(sku_rows), "active_leaf_skus": sum(not s["discontinued"] for s in sku_rows), "items": sku_rows})
    for name, rows in [("manifest.jsonl", manifest), ("recording_plan.jsonl", recording_plan)]:
        (HERE / name).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    customer_channels = defaultdict(set)
    customer_counts = Counter()
    for row in manifest:
        customer_channels[row["customer_id"]].add(row["channel"])
        customer_counts[row["customer_id"]] += 1
    coverage["counts"] = {"scenarios": len(coverage["scenarios"]), "transcripts": len(manifest), "utterances": total_utterances, "customers": len(customers), "multi_session_customers": sum(n >= 2 for n in customer_counts.values()), "customers_with_three_call_journey": len({s["customer_id"] for s in coverage["scenarios"] if len(s["call_ids"]) >= 3}), "call_and_chat_customers": sum("hotline" in cs and bool(cs - {"hotline"}) for cs in customer_channels.values()), "channels": dict(Counter(r["channel"] for r in manifest)), "personas": dict(Counter(s["persona"] for s in coverage["scenarios"])), "catalog_categories": sorted({s["category"] for s in sku_rows}), "active_catalog_leaf_skus": sum(not s["discontinued"] for s in sku_rows), "recording_targets": len(recording_plan), "voice_regions_planned": dict(Counter(r["customer_voice_region"] for r in recording_plan)), "noisy_recordings_planned": sum(r["noise_required"] for r in recording_plan), "estimated_recording_seconds_at_150_words_per_minute": round(sum(r["estimated_seconds_at_150_words_per_minute"] for r in recording_plan), 1), "actual_two_speaker_recordings": 0, "actual_recorded_seconds": 0}
    coverage["counts"]["call_and_chat_customers_within_journey"] = len({s["customer_id"] for s in coverage["scenarios"] if "hotline" in s["channels"] and len(set(s["channels"])) > 1})
    coverage["counts"]["customers_with_two_hotline_calls_in_journey"] = len({s["customer_id"] for s in coverage["scenarios"] if s["channels"].count("hotline") >= 2})
    coverage["source_sha256"] = sources
    coverage["numbering"] = {
        "source_max_scenario_id": f"SC-{SOURCE_SCENARIO_MAX:03d}",
        "first_scenario_id": coverage["scenarios"][0]["scenario_id"],
        "last_scenario_id": coverage["scenarios"][-1]["scenario_id"],
        "count": len(coverage["scenarios"]),
    }
    coverage["limitations"] = ["Synthetic authored dialogues are not agent outputs, simulator runs, measured metrics, recordings or diarization labels.", "Existing customer-only WAV files do not match these expanded two-speaker transcripts and are not counted.", "Catalog passes the SKU minimum when distinct size/color variant SKUs count; there are 40 parent product models, not 100 models.", "Agent performance, ASR, diarization, runtime simulator, human semantic review and completed noisy recordings remain separate work.", "Repeated BTC identities across source scenarios are counted once and scenarios run in isolation; only 36 newly authored identities increase unique-customer coverage."]
    write(HERE / "coverage.json", coverage)
    write(HERE / "requirements.json", {"source_pdf": "../../organizer/SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì.pdf", "source_pdf_sha256": sources["SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì.pdf"], "source_sections": ["C.1 Dữ liệu & xử lý tiếng Việt", "C.4 Đánh giá hệ thống", "Phụ lục B", "DIEU-CHINH-DE.md §§2,8,10,12"], "requirements": {"transcripts": 250, "multi_session_customers": 60, "call_and_chat_customers": 30, "customers_with_three_call_journey": 1, "categories": 3, "catalog_skus": 100, "evaluation_scenarios": 40, "audio_conversations": 100, "audio_duration_seconds": 10800, "voice_regions": 3, "noisy_audio_fraction": 0.2}, "required_personas": ["khach_do_du_hoi_nguoi_nha", "khach_so_gia", "khach_da_mua_doi_size", "khach_hoi_nhieu_khong_mua", "khach_goi_lan_3_het_kien_nhan"], "text_corpus_status": "validate with validate_corpus.py", "audio_status": "pending_recording", "system_m2_status": "not established by authored transcripts"})
    requirements = read(HERE / "requirements.json")
    requirements["requirements"]["customers_with_two_hotline_calls_in_journey"] = 60
    requirements["multi_session_counting"] = "Also enforce at least two hotline calls for 60 distinct customers within a single journey, following the stricter literal call wording of C.1."
    write(HERE / "requirements.json", requirements)
    print(json.dumps(coverage["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build()
