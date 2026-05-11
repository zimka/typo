# TypoChat

**TypoChat** is an AI assistant for the Glyphs font editor, powered by Claude. Describe font issues or design challenges in plain English, and Claude will analyze your glyphs, plan fixes, and apply edits directly to your font — all within Glyphs.

## About

TypoChat brings conversational AI to type design. Instead of manually debugging kerning, spacing, or shape issues, you can ask Claude to help:

- *"The serifs on my f are inconsistent — fix them"*
- *"These nodes are misaligned; tighten them up"*
- *"The spacing looks off between these pairs"*

Claude reads your glyph data, renders samples to verify changes, and proposes edits. You approve or reject each step before it modifies your font.

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/zimka/typo
   cd typo
   ```

2. **Load the plugin in Glyphs:**
   - Double-click `TypoChat.glyphsPlugin`
   - Glyphs will install it automatically

3. **Configure API access:**
   - Open the plugin window (Glyphs → Window → TypoChat)
   - Add your Anthropic API key and endpoint URL

## Quick Start

1. Open a font in Glyphs
2. Open the TypoChat window
3. Describe what you'd like to fix: *"The stroke weight looks uneven in the 'n' glyph"*
4. Claude will analyze, propose changes, and wait for your approval
5. Review the preview and click **Approve** to apply or **Reject** to try another approach

## Configuration

TypoChat requires an Anthropic API key to function. To get started:

1. **Get an API key:**
   - Sign up for an Anthropic account at [console.anthropic.com](https://console.anthropic.com)
   - Generate an API key in your account settings
   - Refer to the [Anthropic API documentation](https://docs.anthropic.com/en/api/getting-started) for details

2. **Add your API key to TypoChat:**
   - Open the TypoChat window in Glyphs
   - Paste your API key in the settings field
   - (Optional) Adjust the API endpoint URL if using a proxy or custom setup

## Development

TBD

## License

TypoChat is licensed under the [MIT License](./LICENSE). See the LICENSE file for details.
