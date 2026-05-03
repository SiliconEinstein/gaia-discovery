---
name: gpt-review
description: "Review a file using GPT-5.4 via the OpenAI-compatible API. Sends the file content to the model and prints a structured review with improvement suggestions. Accepts an optional file path argument; defaults to README.md."
---

# GPT Review

Use GPT-5.4 to review a file and provide improvement suggestions.

The argument provided is: $ARGUMENTS

## Step 1 — Determine the target file and project context

1. If `$ARGUMENTS` specifies a file path, use that.
2. Otherwise default to `README.md` in the repo root.
3. Verify the file exists. If not, report the error and stop.
4. **Read project context**: Find and read `CLAUDE.md` in the repo root (or nearest ancestor). Extract the "Project Overview" section. If no CLAUDE.md exists, use the repo directory name as context.

## Step 2 — Call the API

Send the file contents to GPT-5.4 via the GPUGeek **predictions** endpoint.

**IMPORTANT**: This endpoint uses a **different format** from the OpenAI chat
completions API. Do NOT use `messages` array. Use `input.prompt` instead.

- **API key**: Read from `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` environment variable.
- **Model**: `Vendor2/GPT-5.4`
- **Endpoint**: `POST https://api.gpugeek.com/predictions`

### Request format (predictions API)

```json
{
    "model": "Vendor2/GPT-5.4",
    "input": {
        "prompt": "<system prompt>\n\n<user message with file contents>",
        "max_tokens": 4096,
        "temperature": 0.3
    }
}
```

### Response format

```json
{
    "output": "<review text>",
    "metrics": {"input_token_count": ..., "output_token_count": ...}
}
```

### System prompt (constructed dynamically)

Concatenated with file contents into `input.prompt`:

```
You are reviewing a file from this project:
<insert project context from CLAUDE.md "Project Overview" section>

Before reviewing technical details, first assess:
1. Is this needed at all? Could a simpler approach work?
2. Is this over-engineered or prematurely abstracted?
3. Are resource costs (disk/memory/time) considered?
4. Are parameter choices explained from first principles, not just copied?

Then provide a creative review — suggest alternative approaches, novel simplifications,
or unconventional improvements. Think outside the box.
Structure your response as:
- Necessity Assessment (is this the right thing to build?)
- Creative Alternatives (what else could work?)
- Specific Improvements (concrete suggestions)
```

### Convenience script

```bash
python3 scripts/dev/review_gpt.py <target-file>
```

If the script is missing or fails, construct the API call directly using
the request format above. Common mistake: using `messages` array instead of
`input.prompt` — this returns `400 Bad Request`.

## Step 3 — Present the results

Show the full review output to the user. If the API call fails (missing key, network error, model unavailable), report the error clearly and suggest checking the environment variables.
