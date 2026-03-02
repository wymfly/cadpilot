## ADDED Requirements

### Requirement: SFT formatter converts corrections to Chat JSONL
The system SHALL provide a script that converts cleaned correction data into Qwen Chat SFT format.

#### Scenario: JSONL format for Qwen Chat SFT
- **WHEN** `sft_formatter.py` processes `corrections_clean.jsonl`
- **THEN** each output line SHALL be a JSON object with a `messages` array containing system/user/assistant roles
- **AND** the user message SHALL contain the original spec (as-is or serialized)
- **AND** the assistant message SHALL contain the corrected spec fields applied to the original

#### Scenario: System prompt includes domain context
- **WHEN** the formatter generates the system message
- **THEN** the system prompt SHALL describe the CADPilot domain: "You are a CadQuery code generation assistant for 3D printable parts..."
- **AND** the prompt SHALL include the relevant part_type context

#### Scenario: Output split into train/eval sets
- **WHEN** the formatter completes
- **THEN** the output SHALL be split into `train.jsonl` (90%) and `eval.jsonl` (10%)
- **AND** the split SHALL be deterministic (seeded random)

### Requirement: SFT config defines training hyperparameters
The system SHALL provide a configuration file with default LoRA fine-tuning parameters.

#### Scenario: Config specifies LoRA parameters
- **WHEN** `sft_config.py` is loaded
- **THEN** the config SHALL include `base_model`, `lora_rank`, `lora_alpha`, `learning_rate`, `epochs`, `batch_size`
- **AND** defaults SHALL target Qwen2.5-Coder-7B with rank=16, alpha=32, lr=2e-4, epochs=3
