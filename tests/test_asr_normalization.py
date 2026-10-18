"""Vietnamese ASR normalization examples and ambiguity regressions."""

from pathlib import Path
import sys
import unittest
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from telesale_agent.application.asr_normalization import normalize_asr_transcript
from telesale_agent.adapters.rules.pii_utils import mask_pii


class ASRNormalizationTests(unittest.TestCase):
    def check_cases(self, cases):
        for spoken, expected in cases:
            with self.subTest(spoken=spoken):
                normalized = normalize_asr_transcript(spoken)
                self.assertEqual(normalized, expected)
                self.assertEqual(normalize_asr_transcript(normalized), normalized)

    def test_user_examples(self):
        self.check_cases([
            ("bốn triệu tám trăm chín mươi", "4.890.000"),
            ("hai trăm bốn chín k", "249.000"),
            ("Ngày mười bảy tháng mười năm hai không hai sáu", "17/10/2026"),
            ("Không chín tám bốn bảy hai sáu bảy một bốn", "0984726714"),
        ])

    def test_money_in_real_sentences(self):
        self.check_cases([
            ("GIÁ HIỆN TẠI CÓ PHẢI SÁU TRĂM CHÍN MƯƠI NGHÌN ĐỒNG KHÔNG", "giá hiện tại có phải 690.000 đồng không"),
            ("ngân sách bốn triệu tám trăm chín mươi đồng", "ngân sách 4.890.000 đồng"),
            ("hai trăm bốn mươi chín nghìn", "249.000"),
            ("một trăm linh năm ngàn đồng", "105.000 đồng"),
            ("ba trăm lẻ bảy nghìn", "307.000"),
            ("hai triệu năm trăm nghìn", "2.500.000"),
            ("hai triệu năm trăm", "2.500.000"),
            ("hai triệu năm", "2.500.000"),
            ("hai triệu rưỡi", "2.500.000"),
            ("hai trăm rưỡi nghìn", "250.000"),
            ("hai rưỡi triệu", "2.500.000"),
            ("bốn phẩy tám chín triệu", "4.890.000"),
            ("2,5 triệu", "2.500.000"),
            ("2.5 triệu", "2.500.000"),
            ("249k", "249.000"),
            ("249 k không?", "249.000 không?"),
            ("4 triệu 890 nghìn", "4.890.000"),
            ("4 triệu 890", "4.890.000"),
            ("1.234.567 đồng", "1.234.567 đồng"),
            ("hai tỷ ba trăm triệu", "2.300.000.000"),
            ("một nghìn lẻ hai đồng", "1.002 đồng"),
            ("bốn triệu không trăm linh năm đồng", "4.000.005 đồng"),
        ])

    def test_dates_validate_calendar_and_preserve_unspecified_year(self):
        self.check_cases([
            ("hẹn gọi lại ngày mười bảy tháng mười năm hai không hai sáu nhé", "hẹn gọi lại 17/10/2026 nhé"),
            ("ngày mười bảy tháng mười năm hai nghìn không trăm hai mươi sáu", "17/10/2026"),
            ("ngày 17 tháng 10 năm 2026", "17/10/2026"),
            ("ngày hai mươi lăm tháng năm", "25/05"),
            ("mùng một tháng giêng", "01/01"),
            ("ngày ba mươi mốt tháng chạp", "31/12"),
            ("ngày hai mươi chín tháng hai năm hai không hai bốn", "29/02/2024"),
            ("ngày hai mươi chín tháng hai năm hai không hai sáu", "ngày hai mươi chín tháng hai năm hai không hai sáu"),
            ("ngày ba mươi mốt tháng hai", "ngày ba mươi mốt tháng hai"),
            ("ngày mười bảy tháng mười ba", "ngày mười bảy tháng mười ba"),
            ("ngày mai gọi lại lúc hai giờ chiều", "ngày mai gọi lại lúc hai giờ chiều"),
            ("gọi lại 17/10/2026", "gọi lại 17/10/2026"),
        ])

    def test_phone_numbers_keep_leading_zero(self):
        self.check_cases([
            ("số điện thoại là không chín tám bốn bảy hai sáu bảy một bốn nhé", "số điện thoại là 0984726714 nhé"),
            ("số 0984 726 714", "số 0984726714"),
            ("số 0984.726.714", "số 0984726714"),
            ("0984 bảy hai sáu bảy một bốn", "0984726714"),
            ("KHÔNG CHÍN TÁM BỐN BẢY HAI SÁU BẢY MỘT BỐN. MỘT ÁO", "0984726714. một áo"),
            ("+84 984 726 714", "0984726714"),
            ("cộng tám bốn chín tám bốn bảy hai sáu bảy một bốn", "0984726714"),
        ])

    def test_ambiguous_counts_and_product_names_are_not_money(self):
        self.check_cases([
            ("MẪU WIN BREAK SIVESBOM MÀU XANH NIVE", "mẫu win break sivesbom màu xanh nive"),
            ("hai áo và ba đôi giày", "hai áo và ba đôi giày"),
            ("bốn trăm chín mươi", "bốn trăm chín mươi"),
            ("hai triệu người", "hai triệu người"),
            ("một nghìn sản phẩm", "một nghìn sản phẩm"),
            ("một nghìn giờ", "một nghìn giờ"),
            ("mã 249k", "mã 249k"),
            ("áo A249K", "áo a249k"),
            ("249kg", "249kg"),
            ("năm hai nghìn hai mươi sáu", "năm hai nghìn hai mươi sáu"),
            ("không chín tám bốn", "không chín tám bốn"),
            ("bốn triệu tám triệu", "bốn triệu tám triệu"),
            ("4 triệu 0,5", "4 triệu 0,5"),
            ("số điện thoại 0984726714 đồng ý nhé", "số điện thoại 0984726714 đồng ý nhé"),
        ])

    def test_phone_is_masked_after_normalization(self):
        text = normalize_asr_transcript("gọi số không chín tám bốn bảy hai sáu bảy một bốn")
        masked, _ = mask_pii(text)
        self.assertNotIn("0984726714", masked)

    def test_combined_utterance(self):
        self.check_cases([
            (
                "NGÂN SÁCH BỐN TRIỆU TÁM TRĂM CHÍN MƯƠI ĐỒNG, SỐ ĐIỆN THOẠI KHÔNG CHÍN TÁM BỐN BẢY HAI SÁU BẢY MỘT BỐN, HẸN NGÀY MƯỜI BẢY THÁNG MƯỜI NĂM HAI KHÔNG HAI SÁU",
                "ngân sách 4.890.000 đồng, số điện thoại 0984726714, hẹn 17/10/2026",
            ),
        ])

    def test_whitespace_unicode_and_empty_text(self):
        self.assertEqual(normalize_asr_transcript(""), "")
        self.assertEqual(normalize_asr_transcript("  EM\n MUỐN  MUA\tÁO  "), "em muốn mua áo")
        self.assertEqual(normalize_asr_transcript(unicodedata.normalize("NFD", "SÁU TRĂM NGHÌN")), "600.000")


if __name__ == "__main__":
    unittest.main()
