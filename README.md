# InvenTree Loan Manager

A loan and return management plugin for **InvenTree 1.5.x**. It adds a complete
request → approval → handout → return workflow with audit history, barcode/QR
support, due-date reminders, and a role-aware interface for requesters and loan
desk staff.

## Features

- Users can request parts or specific assets **without** InvenTree stock permissions.
- Approvers can review, approve, and reject requests.
- Loan desk staff can hand out items by scanning barcodes or searching the catalog.
- Partial quantities are supported: items are split, moved, and merged back safely.
- Items move to a dedicated **On Loan** location and receive an **On Loan** status.
- While on loan, stock items are excluded from availability and normal allocation flows.
- Direct edits, moves, quantity changes, allocation, and deletion of loaned items are
  blocked by plugin validation.
- Returns support full or partial quantities, condition notes, and restoring the
  original location and status.
- Every request, decision, handout, reminder, renewal, loss, and return is recorded
  in an append-only audit timeline.
- QR codes identify loans; printed receipts include the QR, due date, and signature
  lines.
- Barcode scanning supports USB/keyboard scanners and camera scanning where the
  browser exposes `BarcodeDetector`.
- Optional email notifications; in-app notifications are always available.
- Scheduled due-soon and overdue reminders.
- CSV export for requests and loans.
- Responsive, accessible interface with light and dark mode support.

## Requirements

- InvenTree **1.5.x** (`MIN_VERSION = 1.5.0`, `MAX_VERSION = 1.5.99`)
- Python 3.10+
- `ENABLE_PLUGINS_APP` and `ENABLE_PLUGINS_URL` must be enabled
- Optional for camera scanning: a browser with `BarcodeDetector` support

## Installation

### As a Python package

```bash
pip install inventree-loan
```

Then restart InvenTree, open the plugin management page
(`/web/settings/admin/plugin`), find **InvenTree Loan Manager**, and activate it.

### Editable development install

```bash
pip install -e .
```

Restart the InvenTree server after installation.

#### Docker development workflow

When InvenTree runs in Docker, the container filesystem is ephemeral. Keep the
editable install in a mounted plugin directory and record it in
`data/plugins.txt`:

```text
-e /home/inventree/data/plugins/inventree-loan
```

After changing static assets (the JavaScript UI or CSS), collect them and restart
both the server and the background worker:

```bash
docker exec -w /home/inventree/src/backend/InvenTree inventree-server \
    python manage.py collectplugins
docker restart inventree-server inventree-worker
```

Python and template changes only need the restart. Plugins are discovered at
startup, so a restart is required after any plugin code change.

### Database migration

The plugin uses its own Django app and migrations. After activating the plugin,
run the InvenTree update/migration command for your deployment, for example:

```bash
invoke update
```

or, in a source install:

```bash
python manage.py migrate
```

## Using the plugin

The plugin adds a **Loans** item to the InvenTree navigation bar and a **Loans**
card to the dashboard widget list.

- **Loans (navigation)** opens the native InvenTree Plugins page filtered to
  **InvenTreeLoan**. Select the plugin row to open the standard plugin drawer,
  then expand **Plugin Configuration** to use the Loan Manager console.
- **Loans (dashboard widget)** provides a requester shortcut and an
  **Open loan desk** button that opens the Loan Manager console in a full-screen
  native Mantine modal.
- Requesters use the standalone request form at `/plugin/loan/request/` for new
  requests, their request history, and their own loans.

The internal console is built from standard InvenTree React and Mantine
components, so it follows the instance theme, language, and accessibility
settings. It contains tabs for requests, loans, handout, staff, setup, and
history.

## Initial setup

The plugin needs two stock objects:

1. A dedicated **On Loan** stock location.
2. A custom **On Loan** stock status whose logical value is `Quarantined`
   (so InvenTree treats loaned items as unavailable).

Run the setup action from the **Setup** tab of the Loan Manager console, or use
the management command:

```bash
python manage.py loan_setup --create-location --location-name "On Loan"
```

The command is idempotent and can be re-run safely. It creates the custom status,
creates or selects the location, and saves the location to the plugin settings.

> The custom status is what makes an item unavailable. The location keeps the
> stock history and the return path clear. If the custom status cannot be created,
> the plugin falls back to InvenTree's built-in `Quarantined` status.

## Staff roles

The plugin has its own roles, separate from InvenTree's stock roles:

| Role | Capabilities |
|---|---|
| **Approver** | View all requests/loans, approve or reject requests |
| **Loan desk** | Everything an approver can do, plus hand out, return, renew, mark lost |
| **Loan administrator** | Everything, plus manage staff and plugin setup |

Superusers always have full plugin access.

Grant the first role from the **Staff** tab of the Loan Manager console or with:

```bash
python manage.py loan_add_manager <username> --role admin
```

Only a superuser can grant the **Loan administrator** role through the web UI.
The last active administrator cannot be demoted or removed.

### Optional core stock permission

By default, plugin roles govern handout and return actions. If your organization
requires InvenTree's core stock change permission as well, enable
**Require core stock permission** in the plugin settings. Loan desk users will then
also need the normal InvenTree stock change role.

## Workflows

### Request

1. Open **Loans → New request**.
2. Search the catalog or scan a specific asset.
3. Set quantities, pickup date, return date, and purpose.
4. Accept the responsibility statement and submit.
5. Approvers receive an in-app notification (and email if enabled).

### Approve or reject

Approvers open the Loan Manager console and use the **Requests** tab to
**Approve** or **Reject**. A decision note can be added and is visible to the
requester.

### Hand out

1. Open the **Handout** tab in the Loan Manager console.
2. Choose an approved request.
3. Confirm the due date and submit.
4. Print the receipt or show the loan QR.

The service selects available stock items, moves or splits the requested quantities
to the On Loan location, applies the On Loan status, and records the original
location and status.

### Return

1. Open the **Loans** tab in the Loan Manager console.
2. Choose the loan and select **Return**.
3. Adjust return quantities and select the condition.
4. Confirm.

The item is returned to its original location, the original status is restored, and
the loan is marked partially returned or returned. The returned stock item remains
linked to the loan line for audit history.

### Renew, lose, and overdue

- **Renew** extends the due date, up to the configured maximum.
- **Lost** closes a line and marks the stock item `Lost` without losing history.
- A daily scheduled task sends due-soon and overdue reminders once per period.

## Barcode and QR

Loan QR codes contain a JSON payload:

```json
{"inventree_loan": "<loan-uuid>"}
```

Scanning a loan QR at the loan desk opens the return workflow. Scanning a stock item
barcode delegates to InvenTree's registered barcode plugins, so existing labels
continue to work.

The scanner accepts:

- USB/keyboard-wedge scanners (type + Enter)
- Manual entry
- Camera scanning in browsers that support `BarcodeDetector`

## Stock behavior

- On handout, the item is moved to the On Loan location and its status is changed to
  the custom On Loan status.
- `StockItem.is_in_stock()` becomes false, so the item drops out of available stock
  calculations and normal sales-order/build/transfer allocation flows.
- On return, the original location and status are restored.
- If the custom status is missing, `Quarantined` is used as a safe fallback.
- Direct core edits, moves, quantity changes, customer/order assignment, and deletion
  of loaned stock items are rejected by `ValidationMixin`.
- Superusers and direct database/shell access can always override plugin protections.

## Plugin settings

| Setting | Default | Purpose |
|---|---|---|
| On Loan location | — | Stock location used while items are out |
| On Loan status name | `ON_LOAN` | Internal custom status name |
| Loanable part category | — | Restrict requests to a category tree |
| Request group | — | Restrict who may submit requests |
| Default loan duration | 14 days | Default pickup-to-return period |
| Due soon reminder | 2 days | Reminder lead time |
| Overdue reminder interval | 1 day | Repeat interval for overdue notices |
| Max active loans per user | 0 | 0 means unlimited |
| Max items per request | 25 | Request line limit |
| Require approval | on | Requests must be approved before handout |
| Allow walk-in checkout | on | Desk staff can create direct loans |
| Allow renewals / max renewals | on / 1 | Renewal policy |
| Require responsibility acknowledgement | on | Requester agreement checkbox |
| Require core stock permission | off | Also check InvenTree stock change permission |
| Lock loaned stock items | on | Block core edits/moves/allocations |
| Hide borrower details from requesters | on | Privacy for scanned items |
| Enable email | off | Send emails in addition to in-app notifications |
| Email from address | — | Optional sender override |
| Loan QR prefix | `LOAN:` | Accepted prefix before QR token |
| Catalog page size | 20 | Search result limit |

## Development

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

Run the plugin tests inside an InvenTree environment:

```bash
python manage.py test inventree_loan
```

or with pytest-django:

```bash
pytest inventree_loan
```

The tests expect the plugin app to be enabled, as InvenTree's test runner enables
installed plugins. Tests cover role hierarchy, request visibility, approval
permissions, stock movement, partial returns, and status restoration.

## Packaging

```bash
python -m build
```

The built wheel includes templates, static assets, migrations, and the
`inventree_plugins` entry point.

## Limitations and notes

- The plugin is targeted at InvenTree 1.5.x. Test against 1.6 before widening
  `MAX_VERSION`.
- Plugin roles are separate from InvenTree groups by design; see the optional core
  stock permission setting.
- The custom On Loan status must exist before handout. The setup page and management
  command handle this.
- Returned stock items are not automatically merged into their parent item
  (`merge=False`), which preserves the loan history link. Staff can merge stock
  manually if desired.
- Camera scanning depends on browser support; USB scanners and manual entry always
  work.
- Loan history is append-only in the UI. Use the Django admin only for emergency
  maintenance.
