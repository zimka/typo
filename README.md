# TypoChat

**TypoChat** is a chat assistant that lives inside **Glyphs**. You describe a problem in ordinary language; the assistant reads your font, suggests a step-by-step plan, and can apply edits **only after you explicitly allow it** by typing **Approve**.

TypoChat connects to **OpenAI’s GPT** by default (**Base URL** and **Model** are preset in the plugin). You need an **internet connection** and a **GPT API key** from OpenAI (see Quickstart). Your font file stays on your Mac; only what the session needs is sent to the configured host (see **Privacy** below).

## Requirements

- **Glyphs 3** on **macOS** (same as the Glyphs app).
- **Python** and **Vanilla** modules from Glyphs’ Plugin Manager (see step 0).
- A **stable internet** connection while you chat.

## Quickstart

### 0) Glyphs preparation

TypoChat depends on Glyphs’ own **Python** and **Vanilla** modules (this is Glyphs’ scripting UI stack — not something you install from python.org).

**Plugin Manager (recommended):** **Window → Plugin Manager → Modules**. Find **Python** and **Vanilla**, then click **Install**.

### 1) Plugin installation

Get the plugin from **[GitHub Releases](https://github.com/zimka/typo/releases/)**.

For the current release, download **[TypoChat.glyphsPlugin.zip (v0.3.5)](https://github.com/zimka/typo/releases/download/v0.3.5/TypoChat.glyphsPlugin.zip)**. Unzip it: inside is a single bundle named **`TypoChat.glyphsPlugin`**. **Double-click** that file; Glyphs should install it. If nothing happens, use **Glyphs → Preferences → Add-ons → Install Plugin…** (menu wording may vary slightly by Glyphs version) and choose the same `.glyphsPlugin`.

### 2) OpenAI GPT API key

TypoChat is preset for OpenAI: **Base URL** `https://api.openai.com` and **Model** `gpt-5.4`. You only need a **GPT API key** in most cases.

1. **Create an API key:** Sign in to OpenAI, add a payment method if required, then create a secret key in the account dashboard. See **[OpenAI quickstart](https://developers.openai.com/api/docs/quickstart)**.
2. **Open TypoChat:** **Window → Typo Chat** (the menu label may follow your Glyphs language).
3. Paste the key into **API key** at the top of the window. Leave **Base URL** and **Model** as they are unless you are switching providers (see below).

**Cost:** GPT usage is **billed by OpenAI**, not by TypoChat. Pricing is on OpenAI’s site.

## Other providers and changing hosts

TypoChat talks to any host that exposes the same **chat-completions** HTTP pattern OpenAI uses (several vendors and gateways are compatible).

To switch away from OpenAI:

1. Set **Base URL** to the **root** URL your vendor documents for this API (for OpenAI itself, keep `https://api.openai.com` with **no** extra `/v1` path—TypoChat adds `/v1/chat/completions`). Other hosts may differ; follow their documentation.
2. Set **Model** to the **exact model name** your vendor expects (for example a deployment id or regional model string).
3. Paste that provider’s **API key** (or token) in **API key**.

If something fails after a change, restore **Base URL** `https://api.openai.com` and **Model** `gpt-5.4`, confirm billing and model access on the provider, then try again.

## The TypoChat window

One window combines settings and chat:

| Area | Purpose |
|------|--------|
| **Base URL**, **API key**, **Model**, **Max tokens** | Defaults target OpenAI (`https://api.openai.com`, `gpt-5.4`). Override **Base URL** / **Model** for other hosts. Adjust **Max tokens** only if you need longer replies. |
| **System prompt** | Advanced: instructions to the assistant. Most users can leave the default. |
| **Transcript** | Read-only log of the conversation. |
| **Message** | What you type to the assistant. **Return** sends; **Shift+Return** adds a new line. **⌘Return** also sends. |

Below the message field: **Send**, **More** (e.g. **New chat**, **Reset snapshot**), and **Reset snapshot** when a snapshot exists.

## About

TypoChat is aimed at **targeted fixes and explanations** — spacing hints, outline tweaks, consistency checks — not a full replacement for your eye or for manual drawing.

Example prompts:

- *"The serifs on my f are inconsistent — fix them."*
- *"These nodes are misaligned; tighten them up."*
- *"The spacing looks off between these pairs."*

The assistant can inspect glyph data and **preview images** it generates so it can reason about shapes. It will propose a **plan** and mark when **approval** is required. Your font is **not** changed until you send **`Approve`** as a message by itself (spacing and capitalization do not matter). If the plan should change, answer in **normal prose**; the assistant revises and asks again.

## Privacy

TypoChat transmits **your messages** and **content retrieved for the assistant**—including **glyph names and outline data**, and **rendered specimen images** when the session requests them—to the **Base URL** you set. That processing is governed by **your provider’s** policies and infrastructure (including any subprocessors they use).

Use TypoChat only for fonts and projects where sending such material to a **third-party service** is permitted under your agreements and obligations.

Your **API key** is stored in **Glyphs’ preferences** on your Mac, in line with other extensions. TypoChat uses it only to authenticate requests to the **Base URL** you entered.

### OpenAI and training data

If your **Base URL** points to **OpenAI**, their API documentation states that customer API data is not used to train models by default. From **[Your data](https://developers.openai.com/api/docs/guides/your-data)**:

> Your data is your data. As of March 1, 2023, data sent to the OpenAI API is not used to train or improve OpenAI models (unless you explicitly opt in to share data with us).

Provider policies and account settings can change; review the current terms on their site when handling sensitive work. **Other hosts** apply their own rules—consult their documentation when you are not using OpenAI.

## Saving your work and undo

- **Save your `.glyphs` file** before long sessions, like any serious edit.
- Use Glyphs’ **Edit → Undo** after changes you dislike.
- When the assistant saves a **snapshot**, you can use **Reset snapshot** (or the **More** menu) to align with the plugin’s compare flow; this is separate from Glyphs’ global undo, so keeping **saved files** and **versions** is still best practice.

## Using TypoChat

1. Open a font.
2. Open **Window → Typo Chat** and confirm your **API key** is set (defaults fill **Base URL** and **Model** for OpenAI).
3. Describe the issue in the **Message** field and press **Send**.
4. When a plan awaits your go-ahead, either send **`Approve`** alone or reply in prose to refine the plan.

## Troubleshooting

| Problem | What to try |
|--------|-------------|
| **“Python” / “Vanilla” errors** | Install both modules from **Plugin Manager → Modules**, then restart Glyphs. |
| **HTTP errors or “unauthorized”** | Confirm the key is valid, the account can call the chosen **Model**, and billing is active. |
| **Wrong or empty replies** | For OpenAI, **Base URL** should be `https://api.openai.com` with no path after the host. After switching providers, verify **Base URL** and **Model** match that vendor’s docs. |
| **Plan never runs** | You must send **`Approve`** on its own once you accept the plan. |
| **Stuck or slow** | **Cancel** if shown; use **New chat** under **More** to clear context. |

For bugs or features, use **[Issues](https://github.com/zimka/typo/issues)** on the repository.

## Updates

New versions are published on **[Releases](https://github.com/zimka/typo/releases/)**. Download the latest **`TypoChat.glyphsPlugin.zip`**, unzip, and **double-click** the `.glyphsPlugin` again to replace the previous install, or install via **Preferences → Add-ons**.

## Source code

Developers can browse or contribute in the **[typo](https://github.com/zimka/typo)** repository on GitHub.

## License

TypoChat is licensed under the [MIT License](./LICENSE). See the LICENSE file for details.
