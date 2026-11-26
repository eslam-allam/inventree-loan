# InvenTree Loan Manager

A loan and return management plugin for **InvenTree 1.6+** (developed and tested
against InvenTree 1.7.4). It adds a complete request → approval → handout →
return workflow with audit history, barcode/QR support, due-date reminders, and
a role-aware interface for requesters and loan desk staff.

## Features

- A **public request catalogue** that works without an InvenTree account.
- Browse loanable parts by category or search, open part details, and request a
  part and quantity. Specific stock units are assigned by the loan desk.
- Anonymous requesters enter their own name, email, phone, organisation and ID,
  so no InvenTree user account is required.
- Requesters sign at submission. The loan desk captures a second signature at
  handout, and a third at return.
- Approvers can review, approve, and reject requests.
- Approved requests can be packed into a **pickup box or bag** with its own
  reference and QR code, then moved to **Ready for pickup**. The box label is
  printable and shows the box reference, request reference, requester, contents
  and a scannable QR code. A separate printable return sheet gives every packed
  stock item its own QR code for fast return counting.
- The admin console has a **View** action for every request, showing requester
  details, purpose, dates, requested items, notes and the submitted signature
  before approval or handout.
- Loan desk staff can hand out items by scanning barcodes or searching the catalog.
- Trackable/serialized parts are loaned as whole units and returned in full.
  Non-trackable parts support partial quantities; split items are moved to the
  loan location and returned to their original location and status.
- Items move to a dedicated **On Loan** location and receive an **On Loan** status.
- While on loan, stock items are excluded from availability and normal allocation flows.
- Direct edits, moves, quantity changes, allocation, and deletion of loaned items are
  blocked by plugin validation.
- Returns support full or partial quantities, condition notes, and restoring the
  original location and status.
- Every request, decision, handout, reminder, renewal, loss, and return is recorded
  in an append-only audit timeline.
- Every anonymous request gets a secret tracking link showing its status, loan
  progress, and signatures.
- QR codes identify loans and pickup boxes; printed receipts and box labels
  include the QR, references, due date and captured signatures where relevant.
- Barcode scanning supports USB/keyboard scanners and camera scanning where the
  browser exposes `BarcodeDetector`.
- The internal console has a context-aware **Scan** action: scan a pickup box,
  request, loan, stock item or part and it offers the relevant handout, return or
  detail action.
- The public request path and the visibility/required state of core public form
  fields are configurable from plugin settings.
- Administrators can add **arbitrary custom fields** to the public form from a
  **Public form** tab, with text, long text, number, email, phone, date,
  checkbox and dropdown types, required/optional state, help text and ordering.
  Values appear on the request page, printable receipt, public tracking page and
  CSV export.
- Optional email notifications for submitted, approved/rejected, ready for
  pickup, handout, partial return and returned events; in-app notifications are
  always available.
- Scheduled due-soon and overdue reminders.
- CSV export for requests and loans.
- Responsive, accessible interface with light and dark mode support.

## Requirements

- InvenTree **1.6+** (`MIN_VERSION = 1.6.0`, `MAX_VERSION = 1.7.99`)
  - InvenTree 1.5.x does not support plugin-defined React routes, so the native
    **Loans** tab requires an upgrade to 1.6 or newer.
- Python 3.10+
- The global settings `ENABLE_PLUGINS_APP`, `ENABLE_PLUGINS_URL`, and
  `ENABLE_PLUGINS_INTERFACE` must be enabled
  - `ENABLE_PLUGINS_APP` is required for the plugin's models and migrations.
  - `ENABLE_PLUGINS_INTERFACE` is required for the **Loans** tab and native page.
- The public request page (`/plugin/loan/request/`) does **not** require an
  InvenTree account. It must be reachable from the network that will use it.
- Optional for camera scanning: a browser with `BarcodeDetector` support

> **Upgrading from 1.5.x:** enable `ENABLE_PLUGINS_APP` before restarting. Without
> it the plugin can appear in the list but its Django app, tables, and URLs are
> never registered, which produces the intermittent empty/broken pages.

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

Plugin JavaScript, CSS, and templates are served directly from the installed
package through the plugin's own URL (`/plugin/loan/assets/...`). They therefore
do not depend on `collectplugins` and are not left stale by the static-file
cache. Python and template changes need a restart because plugins are discovered
at startup:

```bash
docker restart inventree-server inventree-worker
```

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

The plugin adds a **Loans** tab to the InvenTree navigation bar, a **Loans** card
to the dashboard widget list, and a **Loan Manager** spotlight action.

- **Request equipment** (`/plugin/loan/request/`) is the public catalogue.
  It requires no account. It uses an InvenTree-style table with a collapsible
  category tree, category counts that include subcategories, search, barcode
  input, pagination, and a request drawer. Requesters open item details, choose
  available stock, enter their contact details, sign, and submit. The
  confirmation shows the reference code, tracking link, and a printable
  request receipt.
- **Track a request** (`/plugin/loan/track/`) lets an anonymous requester enter
  the reference code and email address to open their request.
- **Request status** (`/plugin/loan/track/<token>/`) shows the request, loan
  dates, decisions, and captured signatures.
- **Loans (navigation)** opens a native InvenTree page at
  `/web/plugin/loan/management`. It is rendered inside the normal InvenTree
  layout, so the header, navigation, theme, and user menu behave exactly like
  the Stock or Parts pages. Requests and loans use searchable, filterable,
  sortable tables with pagination and CSV export; summary cards show pending,
  approved, active and overdue counts. Signed-in requesters use the same page
  for their requests and loans; the old server-rendered My Requests pages
  redirect here, so there is only one version.
- **Request details** (`/web/plugin/loan/requests/<pk>`) is a full native page,
  like a build-order detail page. It shows requester/contact details, purpose,
  dates, lines, signatures, stock allocations, part/stock links, approval and
  handout actions, and print buttons for request/handout/return receipts.
- **Loans (dashboard widget)** provides a requester shortcut and an
  **Open loan desk** button which opens the same native page.
- The plugin settings page (Admin Center → Plugins → InvenTree Loan Manager)
  uses the same native console for initial setup.
- **Public request path**: plugin setting `Public request path` changes the
  public form from `/plugin/loan/request/` to `/plugin/loan/<slug>/`. The old
  path redirects to the configured one. A full custom domain can be added later
  with a reverse proxy.
- **Public form fields**: phone, organization, ID, project, purpose, notes,
  pickup date and return date can each be **Hidden**, **Optional** or
  **Required** from plugin settings. Name and email remain required for tracking
  and notifications. Signature and responsibility acknowledgement remain
  controlled by their existing toggles.
- **Custom public form fields**: administrators can add any number of extra
  fields in the **Public form** tab. Support text, long text, number, email,
  phone, date, checkbox and dropdown fields, including help text, placeholders,
  required state and display order. Archived fields keep their historical values
  on existing requests. Submitted values are shown on the request page, request
  receipt, public tracking page and in a dedicated column in the request CSV.

The native console adapts to the signed-in user's loan role: requesters see
their own requests and loans, while loan staff additionally see the handout,
staff, setup, and audit-history tabs. Handout and return dialogs require the
borrower's signature. The Staff tab searches InvenTree users by name, username
or email, so you do not need to know the exact username.

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

1. Open the public page at `/plugin/loan/request/` (no account required).
2. Browse categories or search, open a part to see its description and available
   stock items, and add the items you need.
3. Enter your name, email, phone, organisation and optional ID, plus pickup and
   return dates and the purpose.
4. Accept the responsibility statement and sign in the signature box.
5. Send the request. The confirmation includes a secret tracking link.
6. Approvers receive an in-app notification (and email if enabled).

### Allocate stock

Before approval or handout, staff can plan which physical stock items will be
used:

1. Open the request detail page and select **Auto allocate**.
2. Review the allocated stock sub-rows. Each row links to the stock item and
   shows its location and quantity.
3. Use **Allocate** on a line to add a specific stock item manually, or scan
   the stock item's barcode/QR in the allocation dialog. Use **Remove** to
   release an allocation.
4. Use **Clear allocations** to start again.

Allocations are plans, not stock movements. They reduce the reported public
availability, and checkout revalidates them before moving stock. Non-trackable
parts can be allocated partially across stock items; serialized assets are
allocated one unit per stock item. The part name links to the native InvenTree
part page, and each allocation links to its stock item page.

### Approve or reject

Approvers open the Loan Manager console or the request detail page. The detail
view shows the requester, contact details, purpose, dates, items, signature and
stock allocations. **Approve** or **Reject**, optionally adding a decision
note. Anonymous requesters receive the decision at the email address they
provided, and can follow the request through their tracking link.

### Pack and mark ready for pickup

1. Open an approved request. A pickup box reference is created automatically
   when the request is approved.
2. Allocate all requested stock. The ready action is disabled while any line is
   still unallocated.
3. Select **Mark ready for pickup**, optionally enter a box/bag name (for
   example `Shelf A – blue box`) and packing notes.
4. The request moves to **Ready for pickup** and the requester receives an
   in-app notification and email when email is enabled.
5. Select **Print box label** to print an A6 label with the box QR, box
   reference, request reference, requester, contents and pickup date. Attach it
   to the box or bag.

The box reference and name are shown on the request page. The pickup box is
marked **Collected** automatically when the request is handed out.

Use **Print return sheet** to print the A4 contents sheet. It lists every
allocated stock item with its own QR code. Keep it with the box; on return, scan
each item QR in the return counter. Serialized QRs count one unit, while bulk
item QRs count the outstanding quantity for that stock item.

### Hand out

1. Open the **Handout** tab in the Loan Manager console, or open the request
   detail page.
2. Scan the pickup box QR to open the request directly, or select **Hand out**
   on an approved or ready-for-pickup request.
3. Review the request details and have the borrower sign in the signature box.
4. Confirm the handout.
5. Print the **handout receipt** or show the loan QR. The receipt QR code opens
   the request tracking/detail page.

The service selects available stock items, moves or splits the requested quantities
to the On Loan location, applies the On Loan status, and records the original
location and status. The handout signature is stored on the loan and shown on the
requester's tracking page and the printed receipt.

### Return

1. Open the **Loans** tab in the Loan Manager console.
2. Choose the loan and select **Return**.
3. Count returned units by scanning each stock item's barcode/QR, use
   **Count all**, or type the quantities. The counting panel starts at zero and
   shows progress against the outstanding units.
4. Select the condition for each counted line.
5. Ask the borrower to sign, then confirm.
6. Print the **return receipt** from the loan row or request detail page.

The item is returned to its original location, the original status is restored, and
the loan is marked partially returned or returned. The return signature is stored
on the loan. The returned stock item remains linked to the loan line for audit
history.

### Trackable and non-trackable parts

- **Non-trackable parts** are quantity-tracked. A request can ask for part of a
  stock item; the plugin splits the item, moves the split quantity to the loan
  location, and returns it to the original location and status. The returned
  split remains a separate stock item so the loan line keeps its audit link.
- **Trackable/serialized assets** are individual stock items with a serial or
  asset label. Requesters ask for the part by quantity; the approver assigns
  specific serials by selecting or scanning them. Serialized items cannot be
  partially returned.

### Renew, lose, and overdue

- **Renew** extends the due date, up to the configured maximum.
- **Lost** closes a line and marks the stock item `Lost` without losing history.
- A daily scheduled task sends due-soon and overdue reminders once per period.

## Barcode and QR

Loan QR codes contain a JSON payload:

```json
{"inventree_loan": "<loan-uuid>"}
```

Loan QR codes can still open the return workflow at the desk. Printed request,
handout, and return receipts use a separate QR code that links to the request
tracking/detail page. Scanning a stock item barcode delegates to InvenTree's
registered barcode plugins, so existing labels continue to work.

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
| Request group | — | Restrict signed-in users on the account pages; public requests remain open |
| Default loan duration | 14 days | Default pickup-to-return period |
| Public request path | `request` | Public form URL segment under `/plugin/loan/` |
| Public form fields | mixed | Hidden / optional / required per core field |
| Custom form fields | none | Add arbitrary fields in the Public form tab |
| Due soon reminder | 2 days | Reminder lead time |
| Overdue reminder interval | 1 day | Repeat interval for overdue notices |
| Max active loans per user | 0 | 0 means unlimited |
| Max items per request | 25 | Request line limit |
| Require approval | on | Requests must be approved before handout |
| Allow walk-in checkout | on | Desk staff can create direct loans |
| Allow renewals / max renewals | on / 1 | Renewal policy |
| Require responsibility acknowledgement | on | Requester agreement checkbox |
| Allow public requests | on | Allow requests without an InvenTree account |
| Require a signature on requests | on | Requester must sign before submitting |
| Require a signature on handout | on | Borrower must sign when items are issued |
| Require a signature on return | on | Borrower must sign when items are returned |
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
python manage.py test inventree_loan
```

The tests expect the plugin app to be enabled, as InvenTree's test runner enables
installed plugins. Tests cover role hierarchy, request visibility, approval
permissions, automatic/manual allocation, public availability limits,
serialized stock rules, checkout, partial returns, and status restoration.

## Packaging

```bash
python -m build
```

The built wheel includes templates, static assets, migrations, and the
`inventree_plugins` entry point.

## Limitations and notes

- The plugin targets InvenTree 1.6–1.7. Test against a new major series before
  widening `MAX_VERSION`.
- Plugin roles are separate from InvenTree groups by design; see the optional core
  stock permission setting.
- The custom On Loan status must exist before handout. The setup page and management
  command handle this.
- Returned stock items are not automatically merged into their parent item
  (`merge=False`), which preserves the loan history link. Staff can merge stock
  manually if desired.
- Camera scanning depends on browser support; USB scanners and manual entry always
  work.
- The public catalogue intentionally exposes part names, descriptions, stock
  locations and available quantities. It does not expose pricing, suppliers,
  borrower details, or other users.
- Loan history is append-only in the UI. Use the Django admin only for emergency
  maintenance.
