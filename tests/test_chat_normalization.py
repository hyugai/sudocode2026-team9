"""Typed input preprocessing without network calls or a language model."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from telesale_agent.application.chat_normalization import normalize_chat_text


class ChatNormalizationTests(unittest.TestCase):
    def check_cases(self, cases):
        for typed, expected in cases:
            with self.subTest(typed=typed):
                normalized = normalize_chat_text(typed)
                self.assertEqual(normalized, expected)
                self.assertEqual(normalize_chat_text(normalized), normalized)

    def test_user_example_and_common_shorthand(self):
        self.check_cases([
            ("sp nay co ship cod k a", "Sản phẩm này có ship cod không anh"),
            ("san pham nay co ship cod khong a", "Sản phẩm này có ship cod không anh"),
            ("SP NAY CO SHIP COD K A", "Sản phẩm này có ship cod không anh"),
            ("mik muon mua ao, shop co hang ko?", "Mình muốn mua áo, shop có hàng không?"),
            ("cho minh xem sp nay vs", "Cho mình xem sản phẩm này với"),
            ("ck dc k a", "chuyển khoản được không anh"),
            ("ib minh gia sp nay", "Inbox mình giá sản phẩm này"),
            ("gia bn tien?", "Giá bao nhiêu tiền?"),
        ])

    def test_code_switching_uses_canonical_shopping_terms(self):
        self.check_cases([
            ("minh muon order ao size xl, shop co freeship k?", "Mình muốn order áo size XL, shop có miễn phí ship không?"),
            ("sale nay con sz m k", "Sale này còn size M không"),
            ("in box minh phi ship", "Inbox mình phí ship"),
            ("shop co free-ship va ship-cod k?", "Shop có miễn phí ship và ship cod không?"),
            ("order nay giao khi nao", "Order này giao khi nào"),
            ("sale off 20%", "Sale 20%"),
            ("can you ship to me?", "Can you ship to me?"),
            ("I can order size M", "I can order size M"),
        ])

    def test_restore_common_unaccented_phrases_in_context(self):
        self.check_cases([
            ("shop co chinh sach doi tra k", "Shop có chính sách đổi trả không"),
            ("minh can doi size va doi mau", "Mình cần đổi size và đổi màu"),
            ("phi ship bao nhieu, giao hang bao lau?", "phí ship bao nhiêu, giao hàng bao lâu?"),
            ("ao mau hong con size M k", "Áo màu hồng còn size M không"),
            ("hom nay co sale k", "Hôm nay có sale không"),
            ("shop co k?", "Shop có không?"),
            ("ao nay co m", "Áo này cỡ M"),
            ("sp nay con k", "Sản phẩm này còn không"),
            ("sp co mau hong k", "Sản phẩm có màu hồng không"),
            ("minh mua quan ao hong", "Mình mua quần áo hồng"),
            ("chi phi ship bao nhieu", "Chi phí ship bao nhiêu"),
            ("ban co mau xanh k", "Bạn có màu xanh không"),
        ])

    def test_protect_identifiers_numbers_names_and_literal_text(self):
        self.check_cases([
            ("sp ma SP-249K gia 249k k a", "Sản phẩm ma SP-249K giá 249k không anh"),
            ("sp gia 249 k k a", "Sản phẩm giá 249 k không anh"),
            ("mã SP size K", "mã SP size K"),
            ("minh can size S va size L", "Mình cần size S và size L"),
            ("sdt 0984726714, hen 17/10/2026", "Số điện thoại 0984726714, hen 17/10/2026"),
            ("toi ten la nguyen van minh", "Tôi tên là nguyen van minh"),
            ("cho Minh xem sp nay", "Cho Minh xem sản phẩm này"),
            ("https://example.com/sp?size=M&sale=10", "https://example.com/sp?size=M&sale=10"),
            ("sp@shop.example", "sp@shop.example"),
            ('mã "SP" va `k`', 'mã "SP" và `k`'),
            ("\ue0000\ue001", "\ue0000\ue001"),
        ])

    def test_unknown_and_ambiguous_words_are_preserved(self):
        self.check_cases([
            ("ban mau hang", "Ban mau hang"),
            ("dk kh bn", "dk kh bn"),
            ("dia chi quan 1", "Địa chỉ quan 1"),
            ("iPhone 16 Pro vs Galaxy S25", "iPhone 16 Pro vs Galaxy S25"),
            ("áo khoác WinBreak Sivesbom màu Navy", "Áo khoác WinBreak Sivesbom màu Navy"),
            ("", ""),
        ])

    def test_whitespace_is_normalized(self):
        self.assertEqual(normalize_chat_text("  sp\n nay\tco ship cod k a  "), "Sản phẩm này có ship cod không anh")


if __name__ == "__main__":
    unittest.main()
