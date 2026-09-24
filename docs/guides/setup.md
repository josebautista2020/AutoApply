# Setup & Installation

## What You Need

- **Python 3.11 or newer** — [Download from python.org](https://python.org/downloads/)
- **System webview for desktop mode** — Edge WebView2 on Windows, or WebKit on macOS/Linux
- **AI API key** (optional) — For AI-generated resumes and cover letters. Supports Anthropic, OpenAI, Google, or DeepSeek. Configure in Settings → AI Provider.

Without an API key, AutoApply still works — it just uses generic templates instead of tailored documents.

## Install and Run

```bash
# Set up Python
python -m venv venv

# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

python -m pip install -e .

# Install Playwright's Chromium browser (required for job searching/applying)
python -m playwright install chromium

# Launch the PyWebView desktop app
python run.py --gui
```

A native app window opens with the dashboard. For browser-only use, run
`python run.py` and open the local URL printed by the server.

## First Launch: Setup Wizard

On first launch, a wizard walks you through 7 steps:

1. **Personal Info** — Name, email, phone, address, bio, LinkedIn/portfolio URLs. Includes a collapsible **Application Answers** section for screening questions (work authorization, visa sponsorship, years of experience, salary, relocation, start date).
2. **Job Preferences** — Job titles you're targeting, preferred locations, remote preference
3. **Filters** — Minimum salary, keywords to include or exclude
4. **Experience Level** — Mid, senior, staff, etc.
5. **Fallback Resume** — Upload a PDF resume for when no AI provider is configured
6. **Platform Login** — Log into LinkedIn and/or Indeed
7. **Done** — Summary and go to dashboard

Everything is editable later in the Settings tab. The full set of Application Answers (including EEO disclosures) is available in **Settings → Application Answers**.

## Optional international executive search

To search specific countries, add `target_countries` to `search_criteria` in
`~/.autoapply/config.json` after completing the wizard. For example:

```json
"search_criteria": {
  "job_titles": ["Director of Engineering", "Head of Infrastructure", "Principal Cloud Architect", "Director de Ingeniería", "Director de Infraestructura Tecnológica", "Arquitecto Empresarial"],
  "locations": ["Remote"],
  "target_countries": ["United States", "Spain", "Panama", "Colombia"],
  "work_authorization": {"United States": "needs_sponsorship"},
  "executive_mode": true,
  "remote_only": false
}
```

The searchers query each selected country for each title. A listing enters the
review queue only when its location explicitly names one of those countries;
an unqualified `Remote` listing is skipped. International targeting always
requires review before submission, even if `apply_mode` was previously set to
`full_auto`. Confirm work authorization, sponsorship, location restrictions,
salary currency, and every generated claim during that review. The current
salary filter does not convert currencies; leave `salary_min` unset for searches
across currencies.
Include relevant local-language titles for the selected countries. Terms like
`Director de Infraestructura` can refer to buildings and civil engineering;
review the technical scope of each result before applying.

`work_authorization` accepts `authorized`, `needs_sponsorship`, or `unknown`
for each country in `target_countries`. Omitted countries default to unknown.
An explicit "no sponsorship" requirement excludes a vacancy when the applicant
needs sponsorship there. Other vacancies retain an eligibility note in the
review event: the applicant must check legal work authorization, employer
support and remote location limits against the original posting. This is a
screening aid, not a visa determination. Do not set a global Work Authorization
answer in the setup wizard for a multi-country campaign; the same answer may
be false in another country.

With `executive_mode`, ranking allocates up to 35 points to the title, 20 to
location, 25 to leadership terms and 20 to architecture terms in the posting.
English and Spanish equivalents count as one concept, including accented words.
The review card shows the terms that contributed to the score. Missing salary
information earns no points and salary is not compared across currencies.
These are signals about the *role*, not evidence that the applicant meets its
requirements; verify the CV and original posting before approval. The setting
is opt-in, so existing scoring remains unchanged.

## Import a private profile

Before running the bot, preview up to ten LinkedIn results without generating
documents, saving applications, or submitting anything:

```bash
python scripts/preview_search.py --config private/config.json --platform linkedin --country Colombia --title "Director de Ingeniería" --limit 10
```

The JSON output includes filter decisions, country eligibility notes, and
whether a description was extracted. The browser session itself may require
sign-in or verification, and selectors still need validation on the user's
installation. For Indeed, specify `--platform indeed`; portal access may be
blocked by verification. This preview never changes `apply_mode` or starts
the application loop. Repeat with the other countries and titles to cover the
international search; a capped preview of all countries can stop in the first
country. Zero results do not prove that no jobs are available.

Keep personal configuration, experience and CV files outside the public Git
repository. After downloading them to one directory on your computer, run
the importer from the repository checkout (substitute your filenames):

```bash
python scripts/import_profile.py --config private/config.json --resume private/resume.pdf --experience private/experience.md --dry-run
python scripts/import_profile.py --config private/config.json --resume private/resume.pdf --experience private/experience.md
```

The importer validates configuration, copies the CV to
`~/.autoapply/default_resume.pdf`, writes experience text under
`~/.autoapply/profile/experiences/`, and sets an absolute fallback CV path.
It forces Review mode and disables the schedule. If any destination file
already exists, the command stops; use `--replace` to make a dated backup
under `~/.autoapply/backups/` before replacing those files. Run the command
with AutoApply stopped, then verify your settings in the dashboard. This
does not log into job sites or submit applications.

## Log Into Your Job Platforms

This step is important. AutoApply uses a real browser to search and apply, so it needs your login sessions.

1. Start the bot once (hit the **Start** button)
2. A browser window opens in the background
3. Go to LinkedIn and/or Indeed and log in normally
4. Stop the bot

Your login sessions are saved. You won't need to log in again — AutoApply reuses the saved session on future runs.

## Next Steps

1. **[Write your experience files](experience-files.md)** — This is how AutoApply learns about your background to generate tailored resumes
2. **Review your settings** — Make sure job titles and locations match what you want
3. **Start the bot** — Hit Start on the dashboard and watch the activity feed
