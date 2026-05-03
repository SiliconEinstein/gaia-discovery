---
name: gemini-review
description: "Review a file using Gemini-3.1-pro via the OpenAI-compatible API. Sends the file content to the model and prints a structured review with improvement suggestions. Accepts an optional file path argument; defaults to README.md."
---

# Gemini Review

Use Gemini-3.1-pro to review a file and provide improvement suggestions.

The argument provided is: $ARGUMENTS

## Step 1 — Determine the target file and project context

1. If `$ARGUMENTS` specifies a file path, use that.
2. Otherwise default to `README.md` in the repo root.
3. Verify the file exists. If not, report the error and stop.
4. **Read project context**: Find and read `CLAUDE.md` in the repo root (or nearest ancestor). Extract the "Project Overview" section. If no CLAUDE.md exists, use the repo directory name as context.

## Step 2 — Call the API

Send the file contents to Gemini-3.1-pro via the **OpenAI-compatible chat completions** endpoint.

**IMPORTANT**: This uses the standard OpenAI `messages` format, NOT the
predictions API format used by `/gpt-review`. Do not confuse the two.

- **Base URL**: Read from `OPENAI_BASE_URL` or `ANTHROPIC_BASE_URL` environment variable.
- **API key**: Read from `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` environment variable.
- **Model**: `Vendor2/Gemini-3.1-pro`
- **Endpoint**: `POST {base_url}/v1/chat/completions`

### Request format (OpenAI chat completions)

```json
{
    "model": "Vendor2/Gemini-3.1-pro",
    "messages": [
        {"role": "system", "content": "<system prompt>"},
        {"role": "user", "content": "<file contents>"}
    ],
    "max_tokens": 4096,
    "temperature": 0.3
}
```

### Response format

```json
{
    "choices": [{"message": {"content": "<review text>"}}],
    "usage": {"prompt_tokens": ..., "completion_tokens": ...}
}
```

### System prompt (constructed dynamically)

```
You are reviewing a file from this project:
<insert project context from CLAUDE.md "Project Overview" section>

Before reviewing technical details, first assess:
1. Is this needed at all? Could a simpler approach work?
2. Is this over-engineered or prematurely abstracted?
3. Are resource costs (disk/memory/time) considered?
4. Are parameter choices explained from first principles, not just copied?

Then provide a technical review with concrete improvement suggestions.
Structure your response as:
- Necessity Assessment (is this the right thing to build?)
- Design Quality (is it built right?)
- Specific Improvements (concrete suggestions)
```

### Convenience script

```bash
python3 scripts/dev/review_gemini.py <target-file>
```

If the script is missing or fails, construct the API call directly using
the request format above. Common mistake: using the predictions API format
(`input.prompt`) instead of the chat completions format (`messages`) — these
are two different GPUGeek endpoints.

## Step 3 — Present the results

Show the full review output to the user. If the API call fails (missing key, network error, model unavailable), report the error clearly and suggest checking the environment variables.
