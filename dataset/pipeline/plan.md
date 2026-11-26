# stage-1: blueprints generation
## code rule:
- Do not create manifest files, lockfiles, SHA-256 checksums, or metadata wrappers.

## dir structure:
- generate.ipynb (main file as entry point)
    - use unique addresses for unique customers (use real addresses matching with customers' region)
    - no masking customers' PII
- input/<neccessary files for input>
- output/
    - use JSONL format to store blueprints
    - files referenced by the blueprints
- src/
    - helper python files

## reports:
- use the following structure to make report
    - dir structure of stage with listed files (highligh files not provided by BTC and created by user by ``)
        - 2 tables below with short description: 1 for btc's files, 1 for the others
    - describe generated blueprints by 2 axes (persona and journey pattern)
    - use 1 sample for each output file as demonstration

# stage-2: transcripts generation
## report:
- report for generation and validation should be seperated in the report file for stage-2
- each phase will be a separate section

## phase-1: load the blueprints + generate transcripts + perform "code check" (format check)
### code rule:
- Do not create manifest files, lockfiles, SHA-256 checksums, or metadata wrappers.
- use batch processing pattern ( 1 batch will include a number of journeys)

### What's to check
- Valid JSON. The response is one JSON object with exactly the session keys in the blueprint, such as call_1 and call_2.
- Valid turns. Each session contains 2–5 nonempty, single-line strings.
- Clean dialogue format. Turns contain no speaker-label prefixes such as Nhân viên: and no unfilled placeholders such as [địa chỉ].

### hardware settings
- utilize 2 GPUs on Kaggle

### AI model
- use existing model in Kagle
- Qwen

### dir structure
- generate.ipynb (main file as entry point) 
- input/<neccessary input files from stage-1>
- output/
- src/
    - helper python files

### testing
- batch-size = 2, journeys = 5

### reports:
- passed/failed generated transcripts
- categorize failed transcripts (if exists)

## phase-2: load the candidates transcript + perform AI check (DeepEval)
### code rule:
- Do not create manifest files, lockfiles, SHA-256 checksums, or metadata wrappers.
- use batch processing pattern ( 1 batch will include a number of journeys)
- use isolated environment for potential dependency errors

### What's to check
- Session goal coverage
- Required fact accuracy and completeness
- Placement of new or changed facts in the correct session
- Continuity across sessions
- Customer-only speaker role
- Fit with the assigned customer persona (threshold = 0.7)
- Natural Vietnamese for the channel, whether hotline or chat (threshold = 0.7)

### hardware settings
- utilize 2 GPUs on Kaggle

### AI model
- use existing model in Kagle
- Gemma 4

### dir structure
- validate.ipynb (main file as entry point) 
- input/<neccessary input files from previous phase 1>
- output/
- src/
    - helper python files

### testing
- batch-size = 2, journeys = 5

### reports:
- passed/failed validated transcripts
- categorize failed validated transcripts (if exists)

# stage-3: dataset finalization
## code rule:
- Do not create manifest files, lockfiles, SHA-256 checksums, or metadata wrappers.
- use batch processing pattern ( 1 batch will include a number of journeys)

## what's to do
- do not perform masking any PII
- join stage-1 data
- deduplicate journeys (use TF-IDF, threshold = 0.9)
- write audit reports
- make file name consecutive (log changes as JSONL)
- fomat for each json file:
```
    Scenario
      scenario_id: string
      level: "M1" | "M2"
      persona: string
      hard_case: string | null
      customer_phone: string
      customer_name: string
      honorific: string
      notes: string
      calls:
        call_1: Session
        call_2: Session
        call_3?: Session
    
    Session
      channel: "hotline" | "chat_fanpage" | "zalo_oa"
      channel_identity: string
      call_date?: "YYYY-MM-DD"
      days_later?: integer
      customer_goal?: string
      customer_turns: string[]
      customer_turns_asr?: string[]
      input_mode?: string
      seed_history?: prior CRM history
      facts_established?: object
      must_carry_over?: string[]
      must_not_ask?: string[]
      ground_truth_facts?: object
      memory_expectation?: object
      expected_outcome: "hen_goi_lai" | "chot_don" | "chuyen_may" | "tu_choi"
      success_if:
        tool_called: string | null
        args_match?: object
```

## dir structure
- finalize.ipynb (main file as entry point) 
- input/<neccessary input files from previous stage-2>
- output/
    - each journey will be a separate JSON file and have name format as SC-XXX.json
- src/
    - helper python files

## reports:
- passed/failed transcripts
- summarize the TF-IDF score
