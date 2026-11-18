# Self Agent — learning memory

Ý tưởng và workflow: [knowledge-gap-loop-plan.md](../../docs/implementation/knowledge-gap-loop-plan.md).

```text
End session → đọc history/evidence → detect vấn đề → duyệt và lưu lesson ngắn
Session sau → đọc memory → chọn lesson liên quan → inject trước generate
```

Không có validator/rewrite online, không thay lời đáp thành fallback. Base agent
tự áp dụng lesson cùng dữ liệu/context hiện tại. Streaming giữ nguyên; judge
chỉ chạy riêng khi đánh giá, không can thiệp lời đáp.

## Bật/tắt và memory

`KNOWLEDGE_GAP_LOOP_ENABLED=false` mặc định. Khi tắt không học/inject lesson.
Core, API/web và benchmark cũ không tự bật wrapper.

`SelfAgentHarness(base)` khi bật đọc `lessons/approved/*.md` từ learning root,
refresh ở đầu session mới. Lesson vừa học chỉ dùng ở session sau. Truyền
`lessons=[]` giữ baseline sạch; danh sách lesson tường minh giữ vòng 1 đóng băng.

Memory mặc định:
`data/memory-root/agents/telesales_agent/knowledge_gap_loop/lessons/approved/`.
Snapshot, gap, FAQ ứng viên, test, job và report ở `outputs/self-agent/learning-runtime/`.
Thí nghiệm dùng memory riêng trong output. Tái sử dụng DB/Pinecone hiện có;
không tự publish FAQ hoặc tạo database mới.

## Lesson compact

```markdown
When: A customer asks about a policy condition.
Do: State the condition only from an applicable authoritative source.
Otherwise: Explain which information has not been verified.
```

Lesson mới tiếng Anh, tối đa 100 từ cho title/when/do/otherwise; mỗi field tối đa
360 ký tự. ID/hash/provenance/mechanism và trigger phục vụ trace/routing, không
inject. Nội dung hành vi giống nhau sau chuẩn hóa chữ/whitespace dùng cùng ID,
dù title khác. Model xem tối đa 20 lesson hiện có để tái dùng cách diễn đạt nếu
cùng điều kiện/hành vi; không bảo đảm gộp mọi paraphrase, không gộp điều kiện khác.

Router chọn theo nghĩa/ngữ cảnh, tối đa 3 lesson và 2400 ký tự. Generate chỉ nhận
When/Do/Otherwise, không có transcript hay metadata. File 7-field cũ vẫn đọc được
và rút gọn khi inject; không sửa run cũ. Khuyên chạy vòng 0 mới để học compact.

`mechanism=knowledge_gap` cho thiếu kiến thức/nguồn; `reflection` cho lỗi context,
suy luận/hành động có bằng chứng. Lesson không phải nguồn chính sách. Tiếp tục
dùng customer memory đáng tin; không mặc định quên khách. Lesson sau session
vẫn phải qua kiểm tra, không ép duyệt để có thay đổi.

## Test tập trung 5 SC

Từ repository root:

```powershell
.\scripts\run_self_learning_focus.ps1 -List
.\scripts\run_self_learning_focus.ps1 -Workers 2 -Judge
```

Chọn SC-004, SC-007, SC-012, SC-014, SC-015 từ `dataset/main/scenarios_complete`.
Vòng 0 mới → học → freeze → vòng 1. Hai SC chạy song song, các call trong SC vẫn
tuần tự và giữ user RAM; SC độc lập không chia sẻ user memory. Cùng khách không
chạy đồng thời. Chờ worker vòng 0 kết thúc rồi freeze lesson từ job hợp lệ.
SC lỗi không chặn vòng 1; vòng 1 vẫn chạy toàn bộ SC dự kiến. Không có lesson
thì vẫn chạy nhưng ghi rõ learning_applied=false. Vòng 1 không tự dùng lesson
vừa sinh giữa vòng. `-Strict` ở script parallel khôi phục cách dừng cũ nếu cần.
Prompt gốc và knowledge dùng chung không bị sửa.

Chọn bộ khác:

```powershell
.\scripts\run_self_learning_parallel_two_rounds.ps1 -ScenarioId SC-004,SC-007 -Workers 2 -Judge
```

`run_self_learning_two_rounds.ps1` tuần tự cũng mặc định cùng 5 SC.
`run_self_learning_round1_approved.ps1 -BaselineRun <run> -Judge` chỉ chạy lại SC
baseline hoàn tất có lesson approved, tạo output mới và ghi rõ subset. Không
coi kết quả subset là số liệu toàn bộ dataset.

## Kiểm tra trước batch

```powershell
python -m unittest discover -s tests -p test_self_agent.py -v
```

Sau thay đổi runner/learner cần smoke một session. CLI `self_agent.scenario_runner`
với `--scenario-id SC-004 --limit 1 --first-call-only` và output/learning-root/
runtime-root mới chọn đúng một call; không dùng smoke làm phép đo hai vòng.
Phân biệt rõ provider giả/offline với LLM/DB thật; unit test không chứng minh
model sẽ cải thiện.

## Đọc kết quả

`outputs/self-agent/parallel-two-rounds/<timestamp>/` chứa summary, round0/round1
manifest và report từng call, worker logs/runtime, cùng comparison khi `-Judge`.

`turns[].lesson_trace` có `mode=memory_only`, selected lesson ID/hash/mechanism,
`injected`, `injected_chars`, `response_modified=false`, routing time/usage.
Không còn passed/repaired/fallback online. Xem câu trả lời thực tế để biết agent
có áp dụng đúng không; không dùng số lesson được inject như điểm chất lượng.

Judge Knowledge Gap Loop tách resolved/safely_unresolved/unsupported, giữ verdict
hoặc reference sai ở needs_review. Reflection chưa có quality metric riêng.
Approved không đồng nghĩa lesson đúng tuyệt đối; phải rà cả cải thiện và regression.
Nếu có SC lỗi ở một trong hai vòng, judge chỉ so các SC đủ toàn bộ call ở cả
hai vòng và ghi exclusions. Summary dùng completed_with_failures, không che lỗi
hay tính SC lỗi là đạt. Run đã dừng trước bản sửa không tự resume; dùng script
round1_approved để tận dụng baseline cũ mà không chạy lại vòng 0.
Học/judge sau session không cộng vào latency hội thoại. Routing/inject là chi
phí online riêng; không có request kiểm tra/sửa câu trả lời.

## Review dễ đọc, không gọi thêm LLM

Giữ nguyên lifecycle: chỉ `end_session()` mới enqueue học; routing/inject lesson
ở turn không chạy learner. Không thêm validator hoặc rewrite câu trả lời online.

- Runner scenario tạo `reviews/SC-xxx-call_N.html` và JSON tương ứng sau mỗi
  session, gồm câu trả lời, lesson trace, issue review, job và guardrail.
- Runner parallel hai vòng và approved subset tạo `review.html` / `review.json`
  ở thư mục run, kể cả khi không bật judge hoặc có scenario lỗi. Judge comparison
  cũng tạo review sau khi lưu kết quả chấm.
- HTML hoạt động offline, không có script hay tài nguyên ngoài. Nội dung hội
  thoại, evidence và lesson được escape; vẫn cần bảo vệ file như transcript gốc.

Trong review hai vòng, xem các nhóm **giải quyết được thêm**, **thận trọng hơn
nhưng vẫn chưa giải quyết**, **regression**, **needs review**, **chưa chấm** và
**excluded**. Mỗi lượt có trước/sau, tô diff văn bản, verdict/error/rationale,
claims và citation, evidence hiện tại/trước đó, liên kết đến lesson đã chọn.
Mỗi lesson liên kết ngược đến lượt được inject và nguồn sinh của nó.

Không coi thay đổi văn bản, job done hoặc lesson approved là cải thiện. Cặp thiếu
verdict hợp lệ không vào mẫu chấm; mẫu bằng không được cảnh báo rõ. Verdict vẫn
cần người đọc xác nhận ngữ nghĩa. Reflection chưa có phép đo chất lượng riêng.
Comparison mới khóa hash report đầu vào; nếu artifact đổi, review không dùng
verdict cũ để tính cải thiện. Comparison cũ được ghi rõ thiếu khóa hash.

Dựng lại review từ run cũ mà không chạy lại agent, judge hay DB:

```powershell
$env:PYTHONPATH='src'
python -m self_agent.evaluation.review `
  --round0 outputs/self-agent/parallel-two-rounds/20261117-214900/round0 `
  --round1 outputs/self-agent/approved-round1/20261117-220206/round1 `
  --comparison outputs/self-agent/approved-round1/20261117-220206/comparison.json `
  --output outputs/self-agent/reviews/214900-to-220206/review.html
```

Không truyền `--comparison` thì module tìm `comparison.json` ở thư mục cha của
round1. Chưa có comparison thì review chỉ trình bày trace/thay đổi, không tự chấm.
Chọn output mới, không ghi đè artifact gốc.

## Guardrail chống nhiễm độc learning memory

`guardrails.py` bổ sung các lớp kiểm tra, không thêm request LLM:

- Mọi payload học/routing/judge được nhắc rõ là dữ liệu không đáng tin, gồm cả
  tool result, source, feedback, lesson và output model trước đó.
- Kiểm tra mẫu giả role, override chỉ dẫn, bypass guardrail, tiết lộ bí mật,
  thao túng điểm, executable markup và một số cách che bằng Unicode/tiếng Việt.
- Chặn lesson có mẫu nguy hiểm khi sinh, nạp bank và ngay trước injection.
  File bank lỗi bị bỏ qua, không xóa hay sửa; review liệt kê lỗi để kiểm tra.
- Source chunk có mẫu nguy hiểm không được đưa vào FAQ ứng viên. Transcript gốc
  vẫn giữ làm evidence; input finding là cảnh báo, không phải lỗi nghiệp vụ.
- Learning memory được đặt trong boundary riêng, ghi rõ ưu tiên thấp hơn
  system/developer và không thể cấp consent, quyền tool hay quyền tiết lộ dữ liệu.

`learning.guardrails` lưu version, input findings, lesson/source bị chặn; trace
runtime lưu lesson bị chặn trước injection. Findings chỉ ghi mã và vị trí, không
chép nguyên payload/secret. Run cũ được ghi rõ chưa có trace guardrail.

Đây là phòng vệ nhiều lớp, **không bảo đảm chặn mọi prompt injection**. Mẫu có
thể bỏ sót hoặc báo nhầm; ngữ nghĩa vẫn qua verifier hiện có. Không thay phân
quyền tool của base agent và không dùng guardrail như bằng chứng chính sách.

```powershell
python -m unittest discover -s tests -p 'test_self_agent*.py' -v
```
