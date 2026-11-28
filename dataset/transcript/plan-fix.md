# fix "Sửa nhãn theo lời khách"

- use current M1,M2 and src directories as read-only source

## output

- Write only corrected scenario JSON files to `fixed/M1/` and `fixed/M2/`. Preserve original filenames and `scenario_id` values. For a full TSR comparison, overlay the corrected files onto a copy of the original scenario set.
- Record one entry per changed session in `fixed-audit/changes.jsonl`. Include the source path, `scenario_id`, `call_id`, evidence turn, reason, and the before/after values of the changed fields. Record sessions flagged for review in `fixed-audit/review.jsonl`.
 
## what should be fixed

- remove "schedule.callback" in success_if for scenarios with following stereotypes:
    - Khách sẽ tự gọi lại. “Em sẽ gọi lại lúc 10 giờ mai.” Dù có giờ cụ thể, người chủ động gọi vẫn là khách.
    - Khách đang nhắc chuyện cũ hoặc vừa gọi lại. “Em gọi lại hỏi về đơn hôm qua.” Xử lý yêu cầu hiện tại.
    - Khách chưa đồng ý, đã từ chối hoặc muốn liên hệ qua kênh khác. “Để em suy nghĩ thêm”, “Không cần gọi lại” hoặc “Chị nhắn Zalo cho em nhé.”
    - Ngày giờ hoặc số điện thoại chưa rõ. “Gọi lại cho em hôm nào nhé.” Hỏi đúng thông tin còn thiếu, rồi đặt lịch khi khách xác nhận.

## how to fix

- Read the whole session. If it does not support a callback appointment, set `tool_called` to `null`, set `args_match` to `{}`, and add `schedule.callback` to `must_not_call_tools`. Remove `ground_truth_facts.scheduled_callback_at` if no appointment was established.
- Keep the callback requirement if a later turn in the same session supplies the missing information. When checking whether the customer's phone is available, consider the scenario phone passed by the runner as `customer_hint`.
- Flag a session for review if the customer confirms a valid appointment and later cancels it. The evaluator applies `must_not_call_tools` to the whole session, including the turns before cancellation.
- Preserve other `success_if` conditions and any existing entries in `must_not_call_tools`.

## testing

| File | Session | Expected result |
| --- | --- | --- |
| `M1/SC-002.json` | `call_1` | The customer will call back. A trace that schedules a callback fails. |
| `M1/SC-077.json` | `call_1` | The customer mentions an earlier call. A trace that schedules a callback fails. |
| `M1/SC-051.json` | `call_1` | The customer wants a Zalo message. A trace that schedules a callback fails. |
| `M1/SC-006.json` | `call_1` | The date and time are missing. Verify the agent asks for them before scheduling. |
| `M2/SC-159.json` | `call_1` | Use the original for this positive control. A trace with the correct callback time passes. |

For each of the four relabeled sessions, verify that a complete trace without a callback passes the callback condition and a trace that schedules one fails.
