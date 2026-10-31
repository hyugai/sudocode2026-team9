# sudo_code_2026-group_9

Hệ thống Telesale Agent hỗ trợ hội thoại bằng text và upload ghi âm tiếng Việt, nhận dạng bằng Zipformer chạy local trên CPU.

- [Cài đặt và sử dụng voice input](docs/deployment/local_voice_input.md)
- [Bật realtime voice với Gemini 3.8 Live](docs/deployment/gemini_live.md)
- [Chuẩn hóa tin nhắn gõ tay trước LLM](docs/agent/text_input_normalization.md)
- [Thiết lập PostgreSQL local](docs/deployment/postgresql_self_hosting.md)

Với Gemini, đặt `NLU_THINKING_LEVEL=minimal` và
`DEEPAGENT_THINKING_LEVEL=minimal` trong `.env` để giảm thinking riêng cho NLU
và main agent. Mỗi biến chỉ áp dụng cho thành phần tương ứng; khi bỏ trống,
thành phần đó kế thừa `LLM_THINKING_LEVEL` hoặc mặc định provider. LLM
persister vẫn dùng cấu hình thinking chung. Khởi động lại backend sau khi đổi
cấu hình.
