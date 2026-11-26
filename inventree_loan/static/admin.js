/**
 * Native InvenTree admin UI for the Loan Manager plugin.
 *
 * This module is loaded by InvenTree's plugin UI loader. React and Mantine are
 * provided as globals by the InvenTree frontend, so this file deliberately does
 * not bundle its own copy of either library.
 */

const React = window.React;
const M = window.MantineCore;

const h = React.createElement;
const { useCallback, useEffect, useMemo, useRef, useState } = React;

const STATUS_COLORS = {
    pending: 'yellow',
    approved: 'blue',
    rejected: 'red',
    cancelled: 'gray',
    fulfilled: 'green',
    partially_fulfilled: 'orange',
    active: 'blue',
    partially_returned: 'orange',
    returned: 'green',
    overdue: 'red',
    lost: 'dark'
};

function statusColor(status) {
    return STATUS_COLORS[status] || 'gray';
}

function StatusBadge({ status, label }) {
    return h(
        M.Badge,
        { color: statusColor(status), variant: 'light', size: 'sm' },
        label || status
    );
}

function errorText(error) {
    const data = error?.response?.data;
    if (!data) return error?.message || 'Request failed';
    if (typeof data === 'string') return data;
    if (Array.isArray(data)) return data.join(' ');
    if (data.detail) return data.detail;
    if (data.error) return data.error;
    return Object.entries(data)
        .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(' ') : value}`)
        .join(' · ');
}

function formatDate(value) {
    if (!value) return '—';
    try {
        return new Date(value).toLocaleDateString();
    } catch (_) {
        return value;
    }
}

function formatQty(value) {
    const number = Number(value || 0);
    return number.toLocaleString(undefined, { maximumFractionDigits: 3 });
}

function Loading() {
    return h(M.Center, { py: 'lg' }, h(M.Loader, { size: 'sm' }));
}

function ErrorAlert({ error }) {
    if (!error) return null;
    return h(M.Alert, { color: 'red', title: 'Something went wrong' }, error);
}

function EmptyState({ label }) {
    return h(
        M.Paper,
        { withBorder: true, p: 'xl' },
        h(M.Stack, { align: 'center', gap: 4 }, h(M.Text, { c: 'dimmed' }, label))
    );
}

function useDebounced(value, delay = 300) {
    const [debounced, setDebounced] = useState(value);
    useEffect(() => {
        const timer = window.setTimeout(() => setDebounced(value), delay);
        return () => window.clearTimeout(timer);
    }, [value, delay]);
    return debounced;
}

function buildQuery(params) {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
            query.set(key, String(value));
        }
    });
    return query.toString();
}

function usePagedList(api, endpoint, query, reloadKey) {
    const [result, setResult] = useState({ data: null, total: 0, error: '', loading: true });
    useEffect(() => {
        let active = true;
        setResult((current) => ({ ...current, loading: true, error: '' }));
        const url = query ? `${endpoint}?${query}` : endpoint;
        api.get(url)
            .then((response) => {
                if (!active) return;
                const rows = response.data?.results || [];
                setResult({
                    data: rows,
                    total: Number(response.data?.total ?? rows.length),
                    error: '',
                    loading: false
                });
            })
            .catch((err) => {
                if (!active) return;
                setResult((current) => ({ ...current, error: errorText(err), loading: false }));
            });
        return () => {
            active = false;
        };
    }, [api, endpoint, query, reloadKey]);
    return result;
}

function TableToolbar({ search, onSearch, placeholder, filters = [], actions = null }) {
    return h(
        M.Paper,
        { withBorder: true, p: 'sm' },
        h(
            M.Group,
            { gap: 'sm', align: 'flex-end', wrap: 'wrap' },
            h(M.TextInput, {
                size: 'sm',
                placeholder: placeholder || 'Search…',
                value: search,
                onChange: (event) => onSearch(event.currentTarget.value),
                leftSection: h(M.Text, { size: 'sm', c: 'dimmed' }, '⌕'),
                rightSection: search
                    ? h(M.CloseButton, {
                          size: 'sm',
                          onClick: () => onSearch(''),
                          'aria-label': 'Clear search'
                      })
                    : null,
                style: { flex: '1 1 240px', minWidth: 210 }
            }),
            ...filters.map((filter) =>
                h(M.Select, {
                    size: 'sm',
                    allowDeselect: false,
                    comboboxProps: { withinPortal: true },
                    ...filter,
                    key: filter.key || filter.placeholder,
                    style: { width: filter.width || 170, ...(filter.style || {}) }
                })
            ),
            actions
        )
    );
}

function TableFooter({ total, limit, page, onPage, onLimit, label = 'items' }) {
    const pages = Math.max(Math.ceil(total / limit), 1);
    const singular =
        label === 'staff' ? 'staff' : label.endsWith('s') ? label.slice(0, -1) : label;
    const countLabel = Number(total) === 1 ? singular : label;
    return h(
        M.Group,
        { justify: 'space-between', align: 'center', gap: 'sm', wrap: 'wrap', mt: 'xs' },
        h(
            M.Group,
            { gap: 'xs' },
            h(M.Text, { size: 'sm', c: 'dimmed' }, `${Number(total || 0).toLocaleString()} ${countLabel}`),
            h(M.Select, {
                size: 'xs',
                value: String(limit),
                onChange: (value) => onLimit(Number(value || 25)),
                data: ['10', '25', '50', '100'],
                allowDeselect: false,
                w: 82,
                'aria-label': 'Rows per page'
            })
        ),
        pages > 1
            ? h(M.Pagination, {
                  size: 'sm',
                  total: pages,
                  value: Math.min(page + 1, pages),
                  onChange: (value) => onPage(value - 1)
              })
            : null
    );
}

function SortTh({ label, field, sort, onSort }) {
    const active = sort === field || sort === `-${field}`;
    return h(
        M.Table.Th,
        {
            style: { cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap' },
            onClick: () => onSort(field),
            'aria-sort': active ? (sort.startsWith('-') ? 'descending' : 'ascending') : 'none'
        },
        h(
            M.Group,
            { gap: 4, wrap: 'nowrap' },
            label,
            active ? h(M.Text, { size: 'xs', c: 'dimmed' }, sort.startsWith('-') ? '▼' : '▲') : null
        )
    );
}

function TableShell({ loading, children }) {
    return h(
        M.Paper,
        { withBorder: true, style: { position: 'relative' } },
        h(M.LoadingOverlay, {
            visible: Boolean(loading),
            overlayProps: { backgroundOpacity: 0.35, blur: 1 }
        }),
        h('div', { style: { overflowX: 'auto' } }, children)
    );
}

function filterLabel(hasFilters, emptyLabel, filteredLabel) {
    return hasFilters ? filteredLabel : emptyLabel;
}

function plural(value, singular, pluralForm = `${singular}s`) {
    return `${Number(value || 0).toLocaleString()} ${Number(value) === 1 ? singular : pluralForm}`;
}

function formatDateTime(value) {
    if (!value) return '—';
    try {
        return new Date(value).toLocaleString(undefined, {
            dateStyle: 'medium',
            timeStyle: 'short'
        });
    } catch (_) {
        return value;
    }
}

function StatCard({ label, value, color }) {
    return h(
        M.Paper,
        { withBorder: true, p: 'sm' },
        h(
            M.Stack,
            { gap: 2 },
            h(M.Text, { size: 'xs', c: 'dimmed', tt: 'uppercase', fw: 600 }, label),
            h(M.Text, { size: 'xl', fw: 700, c: color || undefined }, Number(value || 0).toLocaleString())
        )
    );
}

const REQUEST_STATUS_OPTIONS = [
    { value: 'pending', label: 'Pending' },
    { value: 'approved', label: 'Approved' },
    { value: 'partially_fulfilled', label: 'Partially fulfilled' },
    { value: 'fulfilled', label: 'Fulfilled' },
    { value: 'rejected', label: 'Rejected' },
    { value: 'cancelled', label: 'Cancelled' }
];

const REQUEST_ALLOCATION_OPTIONS = [
    { value: 'complete', label: 'Fully allocated' },
    { value: 'incomplete', label: 'Needs allocation' }
];

const REQUEST_SORT_OPTIONS = [
    { value: '-created', label: 'Newest first' },
    { value: 'created', label: 'Oldest first' },
    { value: 'reference', label: 'Reference A–Z' },
    { value: '-reference', label: 'Reference Z–A' },
    { value: '-needed_by', label: 'Pickup: latest' },
    { value: 'needed_by', label: 'Pickup: earliest' },
    { value: '-return_by', label: 'Return date' },
    { value: '-items', label: 'Most items' }
];

const LOAN_STATUS_OPTIONS = [
    { value: 'open', label: 'Open loans' },
    { value: 'overdue', label: 'Overdue' },
    { value: 'due_soon', label: 'Due soon' },
    { value: 'active', label: 'On loan' },
    { value: 'partially_returned', label: 'Partially returned' },
    { value: 'returned', label: 'Returned' },
    { value: 'lost', label: 'Lost' },
    { value: 'cancelled', label: 'Cancelled' }
];

const LOAN_SORT_OPTIONS = [
    { value: '-issued_at', label: 'Newest issued' },
    { value: 'issued_at', label: 'Oldest issued' },
    { value: 'due_at', label: 'Due soonest' },
    { value: '-due_at', label: 'Due latest' },
    { value: 'reference', label: 'Reference A–Z' },
    { value: '-reference', label: 'Reference Z–A' },
    { value: '-items', label: 'Most items' }
];

const EVENT_TYPE_OPTIONS = [
    { value: 'requested', label: 'Request submitted' },
    { value: 'approved', label: 'Request approved' },
    { value: 'rejected', label: 'Request rejected' },
    { value: 'cancelled', label: 'Request cancelled' },
    { value: 'issued', label: 'Loan issued' },
    { value: 'partially_returned', label: 'Partially returned' },
    { value: 'returned', label: 'Loan returned' },
    { value: 'renewed', label: 'Loan renewed' },
    { value: 'due_soon', label: 'Due soon reminder' },
    { value: 'overdue', label: 'Overdue reminder' },
    { value: 'lost', label: 'Item marked lost' },
    { value: 'updated', label: 'Record updated' },
    { value: 'staff_added', label: 'Staff role granted' },
    { value: 'staff_removed', label: 'Staff role removed' },
    { value: 'setup', label: 'Setup changed' }
];

const STAFF_ROLE_OPTIONS = [
    { value: 'approver', label: 'Approver' },
    { value: 'desk', label: 'Loan desk' },
    { value: 'admin', label: 'Loan administrator' }
];

function SignaturePad({ value, onChange, label = 'Signature', required = false }) {
    const canvasRef = useRef(null);
    const drawing = useRef(false);
    const lastPoint = useRef(null);

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const setup = () => {
            const ratio = window.devicePixelRatio || 1;
            const width = Math.max(canvas.clientWidth || 480, 280);
            const height = 150;
            canvas.width = Math.round(width * ratio);
            canvas.height = Math.round(height * ratio);
            const context = canvas.getContext('2d');
            context.setTransform(ratio, 0, 0, ratio, 0, 0);
            context.lineWidth = 2;
            context.lineCap = 'round';
            context.lineJoin = 'round';
            context.strokeStyle = '#17261f';
            if (value) {
                const image = new Image();
                image.onload = () => {
                    context.clearRect(0, 0, width, height);
                    context.drawImage(image, 0, 0, width, height);
                };
                image.src = value;
            }
        };
        const timer = window.setTimeout(setup, 0);
        return () => window.clearTimeout(timer);
    }, [value]);

    const point = (event) => {
        const rect = canvasRef.current.getBoundingClientRect();
        return { x: event.clientX - rect.left, y: event.clientY - rect.top };
    };

    const start = (event) => {
        event.preventDefault();
        drawing.current = true;
        lastPoint.current = point(event);
        canvasRef.current.setPointerCapture?.(event.pointerId);
    };

    const move = (event) => {
        if (!drawing.current) return;
        event.preventDefault();
        const context = canvasRef.current.getContext('2d');
        const next = point(event);
        context.beginPath();
        context.moveTo(lastPoint.current.x, lastPoint.current.y);
        context.lineTo(next.x, next.y);
        context.stroke();
        lastPoint.current = next;
    };

    const end = (event) => {
        if (!drawing.current) return;
        event.preventDefault();
        drawing.current = false;
        lastPoint.current = null;
        onChange?.(canvasRef.current.toDataURL('image/png'));
    };

    const clear = () => {
        const canvas = canvasRef.current;
        const context = canvas.getContext('2d');
        context.clearRect(0, 0, canvas.width, canvas.height);
        onChange?.('');
    };

    return h(
        M.Stack,
        { gap: 4 },
        h(
            M.Text,
            { size: 'sm', fw: 600 },
            label,
            required ? h(M.Text, { component: 'span', c: 'red' }, ' *') : null
        ),
        h('canvas', {
            ref: canvasRef,
            style: {
                width: '100%',
                height: 150,
                border: '1px solid #cbd5cc',
                borderRadius: 2,
                background: '#fff',
                touchAction: 'none',
                cursor: 'crosshair'
            },
            onPointerDown: start,
            onPointerMove: move,
            onPointerUp: end,
            onPointerLeave: end
        }),
        h(
            M.Group,
            { justify: 'space-between' },
            h(M.Text, { size: 'xs', c: 'dimmed' }, value ? 'Signature captured' : 'Sign inside the box'),
            h(M.Button, { size: 'compact-xs', variant: 'default', onClick: clear }, 'Clear')
        )
    );
}

function RequestDetailModal({ context, requestId, onClose, onAction, handoutMode = false, onHandout }) {
    const api = context.api;
    const [detail, setDetail] = useState(null);
    const [error, setError] = useState('');
    const [signature, setSignature] = useState('');
    const [signatureError, setSignatureError] = useState('');
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (!requestId) {
            setDetail(null);
            setSignature('');
            setSignatureError('');
            return;
        }
        let active = true;
        setDetail(null);
        setError('');
        api.get(`/plugin/loan/api/requests/${requestId}/`)
            .then((response) => {
                if (active) setDetail(response.data);
            })
            .catch((err) => {
                if (active) setError(errorText(err));
            });
        return () => {
            active = false;
        };
    }, [api, requestId]);

    const confirmHandout = () => {
        if (!signature) {
            setSignatureError('The borrower must sign before the items are handed out.');
            return;
        }
        setSaving(true);
        setSignatureError('');
        Promise.resolve(onHandout?.(detail.pk, signature))
            .catch((err) => setSignatureError(errorText(err)))
            .finally(() => setSaving(false));
    };

    return h(
        M.Modal,
        {
            opened: Boolean(requestId),
            onClose,
            title: detail ? `Request ${detail.reference}` : 'Request details',
            size: 'xl',
            centered: true
        },
        h(
            M.Stack,
            { gap: 'md' },
            error ? h(ErrorAlert, { error }) : null,
            detail
                ? h(
                      M.Stack,
                      { gap: 'sm' },
                      h(
                          M.Group,
                          { justify: 'space-between', align: 'flex-start' },
                          h(
                              M.Stack,
                              { gap: 2 },
                              h(M.Text, { fw: 700, size: 'lg' }, detail.requester_name || detail.requester),
                              h(M.Text, { size: 'sm', c: 'dimmed' }, detail.requester_email || 'No email provided'),
                              detail.requester_phone
                                  ? h(M.Text, { size: 'sm', c: 'dimmed' }, detail.requester_phone)
                                  : null
                          ),
                          h(StatusBadge, { status: detail.status, label: detail.status_display })
                      ),
                      detail.requester_organization || detail.requester_identifier
                          ? h(
                                M.Text,
                                { size: 'sm', c: 'dimmed' },
                                [detail.requester_organization, detail.requester_identifier]
                                    .filter(Boolean)
                                    .join(' · ')
                            )
                          : null,
                      h(M.Text, null, detail.purpose || 'No purpose provided.'),
                      h(
                          M.Group,
                          { grow: true },
                          h(M.Text, { size: 'sm' }, `Pickup: ${formatDate(detail.needed_by)}`),
                          h(M.Text, { size: 'sm' }, `Return: ${formatDate(detail.return_by)}`),
                          h(M.Text, { size: 'sm' }, `Created: ${formatDate(detail.created)}`)
                      ),
                      detail.notes ? h(M.Text, { size: 'sm', c: 'dimmed' }, detail.notes) : null,
                      h(
                          M.Table,
                          { verticalSpacing: 'xs' },
                          h(
                              M.Table.Thead,
                              null,
                              h(
                                  M.Table.Tr,
                                  null,
                                  h(M.Table.Th, null, 'Part'),
                                  h(M.Table.Th, null, 'Asset'),
                                  h(M.Table.Th, null, 'Qty'),
                                  h(M.Table.Th, null, 'Notes')
                              )
                          ),
                          h(
                              M.Table.Tbody,
                              null,
                              (detail.lines || []).map((line) =>
                                  h(
                                      M.Table.Tr,
                                      { key: line.pk },
                                      h(
                                          M.Table.Td,
                                          null,
                                          h(M.Anchor, { href: line.part_url || '#', target: '_blank', fw: 600 }, line.part_name),
                                          line.ipn ? h(M.Text, { size: 'xs', c: 'dimmed' }, line.ipn) : null
                                      ),
                                      h(
                                          M.Table.Td,
                                          null,
                                          line.stock_item_url
                                              ? h(M.Anchor, { href: line.stock_item_url, target: '_blank' }, line.stock_item_label)
                                              : line.stock_item_label || 'Any available'
                                      ),
                                      h(M.Table.Td, null, line.quantity),
                                      h(M.Table.Td, null, line.notes || '—')
                                  )
                              )
                          )
                      ),
                      detail.decision_notes
                          ? h(M.Alert, { color: 'blue', title: 'Decision notes' }, detail.decision_notes)
                          : null,
                      detail.signature
                          ? h(
                                M.Stack,
                                { gap: 2 },
                                h(M.Text, { size: 'sm', fw: 600 }, 'Submitted signature'),
                                h('img', {
                                    src: detail.signature,
                                    alt: 'Requester signature',
                                    style: {
                                        maxWidth: 280,
                                        border: '1px solid #cbd5cc',
                                        borderRadius: 2,
                                        background: '#fff'
                                    }
                                })
                            )
                          : h(M.Text, { size: 'sm', c: 'red' }, 'No request signature on file.'),
                      handoutMode
                          ? h(SignaturePad, {
                                value: signature,
                                onChange: setSignature,
                                label: 'Borrower signature',
                                required: true
                            })
                          : null,
                      signatureError ? h(M.Text, { size: 'sm', c: 'red' }, signatureError) : null,
                      h(
                          M.Group,
                          { justify: 'flex-end' },
                          h(M.Button, { variant: 'default', onClick: onClose }, 'Close'),
                          !handoutMode && detail.can_approve
                              ? h(
                                    M.Button,
                                    {
                                        color: 'green',
                                        onClick: () => onAction?.({ id: detail.pk, type: 'approve' })
                                    },
                                    'Approve'
                                )
                              : null,
                          !handoutMode && detail.can_approve
                              ? h(
                                    M.Button,
                                    {
                                        color: 'red',
                                        variant: 'light',
                                        onClick: () => onAction?.({ id: detail.pk, type: 'reject' })
                                    },
                                    'Reject'
                                )
                              : null,
                          handoutMode
                              ? h(M.Button, { loading: saving, onClick: confirmHandout }, 'Confirm handout')
                              : detail.can_checkout
                                ? h(
                                      M.Button,
                                      {
                                          onClick: () => onAction?.({ id: detail.pk, type: 'checkout' })
                                      },
                                      'Hand out'
                                  )
                                : null
                      )
                  )
                : h(Loading)
        )
    );
}

function RequestDetailPage({ context, requestId }) {
    const api = context.api;
    const [detail, setDetail] = useState(null);
    const [error, setError] = useState('');
    const [reloadKey, setReloadKey] = useState(0);
    const [busy, setBusy] = useState('');
    const [allocationError, setAllocationError] = useState('');
    const [manualLine, setManualLine] = useState(null);
    const [candidates, setCandidates] = useState(null);
    const [candidateError, setCandidateError] = useState('');
    const [stockItemId, setStockItemId] = useState('');
    const [quantity, setQuantity] = useState(1);
    const [scanValue, setScanValue] = useState('');
    const [scanBusy, setScanBusy] = useState(false);
    const [action, setAction] = useState(null);
    const [notes, setNotes] = useState('');
    const [signature, setSignature] = useState('');
    const [actionError, setActionError] = useState('');
    const [actionBusy, setActionBusy] = useState(false);

    useEffect(() => {
        let active = true;
        setError('');
        setDetail(null);
        api.get(`/plugin/loan/api/requests/${requestId}/`)
            .then((response) => {
                if (active) setDetail(response.data);
            })
            .catch((err) => {
                if (active) setError(errorText(err));
            });
        return () => {
            active = false;
        };
    }, [api, requestId, reloadKey]);

    const reload = () => setReloadKey((value) => value + 1);

    const allocate = (payload) => {
        setBusy('allocate');
        setAllocationError('');
        return api.post(`/plugin/loan/api/requests/${requestId}/allocate/`, payload)
            .then((response) => {
                setDetail(response.data);
                return response.data;
            })
            .catch((err) => {
                setAllocationError(errorText(err));
                throw err;
            })
            .finally(() => setBusy(''));
    };

    const removeAllocation = (allocation) => {
        if (!window.confirm(`Remove ${allocation.quantity} × ${allocation.stock_item_label}?`)) return;
        setBusy(`remove-${allocation.pk}`);
        setAllocationError('');
        api.delete(`/plugin/loan/api/requests/${requestId}/allocations/${allocation.pk}/`)
            .then((response) => setDetail(response.data))
            .catch((err) => setAllocationError(errorText(err)))
            .finally(() => setBusy(''));
    };

    const openManualAllocation = (line) => {
        setManualLine(line);
        setCandidates(null);
        setCandidateError('');
        setStockItemId('');
        setScanValue('');
        setScanBusy(false);
        setQuantity(Number(line.unallocated_quantity) || 1);
        api.get(`/plugin/loan/api/requests/${requestId}/allocations/candidates/?line_id=${line.pk}`)
            .then((response) => setCandidates(response.data))
            .catch((err) => setCandidateError(errorText(err)));
    };

    const selectedCandidate = (candidates?.stock_items || []).find(
        (item) => String(item.pk) === String(stockItemId)
    );

    const scanAllocation = (barcode) => {
        const value = (barcode || '').trim();
        if (!manualLine || !value) return;
        if (!candidates) {
            setCandidateError('Wait for the stock list to load, then scan again.');
            return;
        }
        setScanBusy(true);
        setCandidateError('');
        api.post('/plugin/loan/api/scan/', { barcode: value })
            .then((response) => {
                const found = response.data || {};
                if (!found.success) {
                    setCandidateError(found.error || 'No matching stock item found.');
                    return;
                }
                if (found.type !== 'stockitem') {
                    setCandidateError('Scan a stock item barcode or QR code.');
                    return;
                }
                const item = (candidates.stock_items || []).find(
                    (entry) => String(entry.pk) === String(found.data.pk)
                );
                if (!item) {
                    setCandidateError(
                        `That stock item is not available for ${manualLine.part_name}.`
                    );
                    return;
                }
                setStockItemId(String(item.pk));
                setScanValue('');
                if (item.serialized) {
                    setQuantity(1);
                    allocate({
                        line_id: manualLine.pk,
                        stock_item_id: item.pk,
                        quantity: 1
                    })
                        .then(() => setManualLine(null))
                        .catch(() => {});
                } else {
                    setQuantity(
                        Math.min(
                            Number(item.available) || 1,
                            Number(manualLine.unallocated_quantity) || 1
                        )
                    );
                }
            })
            .catch((err) => setCandidateError(errorText(err)))
            .finally(() => setScanBusy(false));
    };

    const submitManualAllocation = () => {
        if (!manualLine || !selectedCandidate) {
            setCandidateError('Choose a stock item to allocate.');
            return;
        }
        allocate({
            line_id: manualLine.pk,
            stock_item_id: selectedCandidate.pk,
            quantity: selectedCandidate.serialized ? 1 : quantity
        }).then(() => setManualLine(null)).catch(() => {});
    };

    const submitAction = () => {
        if (!action) return;
        if (action === 'checkout' && !signature) {
            setActionError('The borrower must sign before the items are handed out.');
            return;
        }
        setActionBusy(true);
        setActionError('');
        const promise = action === 'checkout'
            ? api.post('/plugin/loan/api/checkout/', {
                  request_id: requestId,
                  notes,
                  signature
              })
            : api.post(`/plugin/loan/api/requests/${requestId}/${action}/`, { notes });
        promise
            .then(() => {
                setAction(null);
                setNotes('');
                setSignature('');
                reload();
            })
            .catch((err) => setActionError(errorText(err)))
            .finally(() => setActionBusy(false));
    };

    const requestReceipt = detail?.public_token
        ? `/plugin/loan/track/${detail.public_token}/receipt/`
        : null;
    const handoutReceipt = detail?.loan_pk
        ? `/plugin/loan/loans/${detail.loan_pk}/receipt/?type=handout`
        : null;
    const returnReceipt = detail?.loan_pk && detail?.loan_status === 'returned'
        ? `/plugin/loan/loans/${detail.loan_pk}/receipt/?type=return`
        : null;
    const canAllocate = Boolean(detail?.can_approve || detail?.can_handout || detail?.can_checkout);
    const fulfilled = Boolean(detail?.loan_pk) || detail?.status === 'fulfilled';

    if (error) {
        return h(M.Stack, { gap: 'md' }, h(ErrorAlert, { error }), h(M.Button, { onClick: () => context.navigate('/plugin/loan/management') }, 'Back to loan desk'));
    }
    if (!detail) return h(Loading);

    return h(
        M.Stack,
        { gap: 'md' },
        h(
            M.Group,
            { justify: 'space-between', align: 'flex-start' },
            h(
                M.Group,
                { gap: 'sm', align: 'center' },
                h(M.Button, { variant: 'default', size: 'xs', onClick: () => context.navigate('/plugin/loan/management') }, 'Back'),
                h(M.Title, { order: 3 }, `Request ${detail.reference}`),
                h(StatusBadge, { status: detail.status, label: detail.status_display })
            ),
            h(
                M.Group,
                { gap: 6, wrap: 'wrap' },
                requestReceipt ? h(M.Anchor, { href: requestReceipt, target: '_blank', size: 'sm' }, 'Print request receipt') : null,
                handoutReceipt ? h(M.Anchor, { href: handoutReceipt, target: '_blank', size: 'sm' }, 'Print handout receipt') : null,
                returnReceipt ? h(M.Anchor, { href: returnReceipt, target: '_blank', size: 'sm' }, 'Print return receipt') : null
            )
        ),
        h(
            M.Paper,
            { withBorder: true, p: 'md' },
            h(
                M.Group,
                { justify: 'space-between', align: 'flex-start' },
                h(
                    M.Stack,
                    { gap: 2 },
                    h(M.Text, { fw: 700 }, detail.requester_name || detail.requester),
                    h(M.Text, { size: 'sm', c: 'dimmed' }, detail.requester_email || 'No email provided'),
                    detail.requester_phone ? h(M.Text, { size: 'sm', c: 'dimmed' }, detail.requester_phone) : null,
                    detail.requester_organization || detail.requester_identifier
                        ? h(M.Text, { size: 'sm', c: 'dimmed' }, [detail.requester_organization, detail.requester_identifier].filter(Boolean).join(' · '))
                        : null
                ),
                h(
                    M.Group,
                    { gap: 'xs' },
                    detail.can_approve ? h(M.Button, { size: 'xs', color: 'green', onClick: () => setAction('approve') }, 'Approve') : null,
                    detail.can_approve ? h(M.Button, { size: 'xs', color: 'red', variant: 'light', onClick: () => setAction('reject') }, 'Reject') : null,
                    detail.can_checkout ? h(M.Button, { size: 'xs', onClick: () => setAction('checkout') }, 'Hand out') : null
                )
            ),
            h(M.Text, { mt: 'sm' }, detail.purpose || 'No purpose provided.'),
            h(
                M.Group,
                { gap: 'lg', mt: 'xs' },
                h(M.Text, { size: 'sm' }, `Pickup: ${formatDate(detail.needed_by)}`),
                h(M.Text, { size: 'sm' }, `Return: ${formatDate(detail.return_by)}`),
                h(M.Text, { size: 'sm' }, `Created: ${formatDate(detail.created)}`)
            ),
            detail.notes ? h(M.Text, { size: 'sm', c: 'dimmed', mt: 'xs' }, detail.notes) : null
        ),
        h(
            M.Paper,
            { withBorder: true, p: 'md' },
            h(
                M.Group,
                { justify: 'space-between', mb: 'sm' },
                h(M.Title, { order: 4 }, 'Requested items'),
                canAllocate && !fulfilled
                    ? h(
                          M.Group,
                          { gap: 'xs' },
                          h(M.Button, { size: 'xs', loading: busy === 'allocate', onClick: () => allocate({ auto: true }) }, 'Auto allocate'),
                          h(M.Button, { size: 'xs', variant: 'default', loading: busy === 'allocate', onClick: () => allocate({ clear: true }) }, 'Clear allocations')
                      )
                    : null
            ),
            h(ErrorAlert, { error: allocationError }),
            h(
                M.Table,
                { verticalSpacing: 'sm' },
                h(
                    M.Table.Thead,
                    null,
                    h(
                        M.Table.Tr,
                        null,
                        h(M.Table.Th, null, 'Part'),
                        h(M.Table.Th, null, 'Requested'),
                        h(M.Table.Th, null, 'Allocated'),
                        h(M.Table.Th, null, 'Outstanding'),
                        h(M.Table.Th, null, 'Available'),
                        h(M.Table.Th, null, 'Actions')
                    )
                ),
                h(
                    M.Table.Tbody,
                    null,
                    (detail.lines || []).map((line) =>
                        h(
                            React.Fragment,
                            { key: line.pk },
                            h(
                                M.Table.Tr,
                                null,
                                h(
                                    M.Table.Td,
                                    null,
                                    h(M.Anchor, { href: line.part_url || '#', target: '_blank', fw: 600 }, line.part_name),
                                    line.ipn ? h(M.Text, { size: 'xs', c: 'dimmed' }, line.ipn) : null
                                ),
                                h(M.Table.Td, null, line.quantity),
                                h(
                                    M.Table.Td,
                                    null,
                                    fulfilled
                                        ? h(M.Badge, { color: 'green', variant: 'light' }, 'Issued')
                                        : h(M.Badge, { color: line.is_fully_allocated ? 'green' : line.allocated_quantity > 0 ? 'yellow' : 'gray', variant: 'light' }, `${line.allocated_quantity} / ${line.quantity}`)
                                ),
                                h(M.Table.Td, null, fulfilled ? '0' : line.unallocated_quantity),
                                h(M.Table.Td, null, fulfilled ? '—' : line.available_stock),
                                h(
                                    M.Table.Td,
                                    null,
                                    h(
                                        M.Group,
                                        { gap: 4, wrap: 'nowrap' },
                                        h(M.Anchor, { href: line.part_url || '#', target: '_blank', size: 'xs' }, 'View part'),
                                        canAllocate && !fulfilled && !line.is_fully_allocated
                                            ? h(M.Button, { size: 'compact-xs', variant: 'light', onClick: () => openManualAllocation(line) }, 'Allocate')
                                            : null
                                    )
                                )
                            ),
                            !fulfilled && (line.allocations || []).length
                                ? h(
                                      M.Table.Tr,
                                      null,
                                      h(
                                          M.Table.Td,
                                          { colSpan: 6 },
                                          h(
                                              M.Stack,
                                              { gap: 4 },
                                              h(M.Text, { size: 'xs', fw: 600, c: 'dimmed' }, 'Allocated stock'),
                                              ...(line.allocations || []).map((allocation) =>
                                                  h(
                                                      M.Group,
                                                      { key: allocation.pk, justify: 'space-between', gap: 'sm' },
                                                      h(
                                                          M.Group,
                                                          { gap: 'sm' },
                                                          h(M.Anchor, { href: allocation.stock_item_url || '#', target: '_blank', size: 'xs' }, allocation.stock_item_label),
                                                          allocation.stock_item_serial ? h(M.Text, { size: 'xs', c: 'dimmed' }, allocation.stock_item_serial) : null,
                                                          h(M.Text, { size: 'xs', c: 'dimmed' }, allocation.location || ''),
                                                          h(M.Text, { size: 'xs' }, `x ${allocation.quantity}`)
                                                      ),
                                                      canAllocate
                                                          ? h(M.Button, { size: 'compact-xs', color: 'red', variant: 'subtle', loading: busy === `remove-${allocation.pk}`, onClick: () => removeAllocation(allocation) }, 'Remove')
                                                          : null
                                                  )
                                              )
                                          )
                                      )
                                  )
                                : null
                        )
                    )
                )
            )
        ),
        h(
            M.Paper,
            { withBorder: true, p: 'md' },
            h(M.Group, { justify: 'space-between', align: 'flex-start' }, h(M.Title, { order: 4 }, 'Signature'), h(M.Badge, { color: detail.signature ? 'green' : 'red', variant: 'light' }, detail.signature ? 'Signed' : 'Missing')),
            detail.signature
                ? h('img', { src: detail.signature, alt: 'Requester signature', style: { maxWidth: 320, marginTop: 8, border: '1px solid #cbd5cc', background: '#fff' } })
                : null,
            detail.decision_notes ? h(M.Alert, { color: 'blue', title: 'Decision notes', mt: 'sm' }, detail.decision_notes) : null
        ),
        detail.loan_pk
            ? h(
                  M.Paper,
                  { withBorder: true, p: 'md' },
                  h(M.Group, { justify: 'space-between' }, h(M.Title, { order: 4 }, `Loan ${detail.loan_reference}`), h(StatusBadge, { status: detail.loan_status, label: detail.loan_status_display })),
                  h(M.Group, { gap: 6, mt: 'xs', wrap: 'wrap' }, handoutReceipt ? h(M.Anchor, { href: handoutReceipt, target: '_blank' }, 'Print handout receipt') : null, returnReceipt ? h(M.Anchor, { href: returnReceipt, target: '_blank' }, 'Print return receipt') : null)
              )
            : null,
        h(
            M.Modal,
            { opened: Boolean(manualLine), onClose: () => setManualLine(null), title: manualLine ? `Allocate ${manualLine.part_name}` : 'Allocate stock', size: 'lg', centered: true },
            h(
                M.Stack,
                { gap: 'sm' },
                h(
                    M.Group,
                    { align: 'flex-end', wrap: 'wrap' },
                    h(M.TextInput, {
                        label: 'Scan to allocate',
                        placeholder: 'Scan a stock item barcode or QR code',
                        value: scanValue,
                        onChange: (event) => setScanValue(event.currentTarget.value),
                        onKeyDown: (event) => {
                            if (event.key === 'Enter') {
                                event.preventDefault();
                                scanAllocation(scanValue);
                            }
                        },
                        style: { flex: '1 1 320px' },
                        description:
                            'Serialized items are allocated immediately. Bulk items are selected for the quantity below.'
                    }),
                    h(
                        M.Button,
                        {
                            variant: 'default',
                            loading: scanBusy,
                            onClick: () => scanAllocation(scanValue)
                        },
                        'Scan'
                    )
                ),
                candidateError ? h(ErrorAlert, { error: candidateError }) : null,
                candidates
                    ? h(M.Select, {
                          label: 'Stock item',
                          placeholder: 'Choose a stock item',
                          data: (candidates.stock_items || []).map((item) => ({
                              value: String(item.pk),
                              label: `${item.label || `Item #${item.pk}`} · ${item.location || 'No location'} · ${item.available} available`
                          })),
                          value: stockItemId,
                          onChange: (value) => {
                              setStockItemId(value || '');
                              const item = (candidates.stock_items || []).find((entry) => String(entry.pk) === String(value));
                              if (item?.serialized) setQuantity(1);
                          },
                          searchable: true
                      })
                    : h(Loading),
                h(M.NumberInput, {
                    label: 'Quantity',
                    min: 0.00001,
                    step: 1,
                    value: quantity,
                    disabled: Boolean(selectedCandidate?.serialized),
                    onChange: (value) => setQuantity(Math.max(Number(value) || 1, 1)),
                    max: selectedCandidate ? Number(selectedCandidate.available) : undefined
                }),
                h(M.Group, { justify: 'flex-end' }, h(M.Button, { variant: 'default', onClick: () => setManualLine(null) }, 'Cancel'), h(M.Button, { loading: busy === 'allocate', onClick: submitManualAllocation }, 'Allocate'))
            )
        ),
        h(
            M.Modal,
            { opened: Boolean(action), onClose: () => setAction(null), title: action === 'checkout' ? 'Hand out request' : action === 'approve' ? 'Approve request' : 'Reject request', centered: true },
            h(
                M.Stack,
                { gap: 'sm' },
                h(M.Textarea, { label: 'Notes', minRows: 3, value: notes, onChange: (event) => setNotes(event.currentTarget.value) }),
                action === 'checkout' ? h(SignaturePad, { value: signature, onChange: setSignature, label: 'Borrower signature', required: true }) : null,
                actionError ? h(M.Text, { size: 'sm', c: 'red' }, actionError) : null,
                h(M.Group, { justify: 'flex-end' }, h(M.Button, { variant: 'default', onClick: () => setAction(null) }, 'Cancel'), h(M.Button, { loading: actionBusy, color: action === 'reject' ? 'red' : action === 'approve' ? 'green' : undefined, onClick: submitAction }, action === 'checkout' ? 'Confirm handout' : action === 'approve' ? 'Approve' : 'Reject'))
            )
        )
    );
}

function RequestsPanel({ context, onDataChanged }) {
    const api = context.api;
    const [reloadKey, setReloadKey] = useState(0);
    const [search, setSearch] = useState('');
    const [status, setStatus] = useState('');
    const [allocation, setAllocation] = useState('');
    const [sort, setSort] = useState('-created');
    const [page, setPage] = useState(0);
    const [limit, setLimit] = useState(25);
    const [action, setAction] = useState(null);
    const [notes, setNotes] = useState('');
    const [saving, setSaving] = useState(false);
    const [actionError, setActionError] = useState('');
    const [signature, setSignature] = useState('');
    const debouncedSearch = useDebounced(search);
    const query = buildQuery({
        search: debouncedSearch.trim(),
        status,
        allocation,
        sort,
        limit,
        offset: page * limit
    });
    const { data: requests, total, error, loading } = usePagedList(
        api,
        '/plugin/loan/api/requests/',
        query,
        reloadKey
    );
    const hasFilters = Boolean(debouncedSearch.trim() || status || allocation);
    const exportQuery = buildQuery({
        search: debouncedSearch.trim(),
        status,
        allocation,
        sort
    });

    const resetPage = () => setPage(0);
    const toggleSort = (field) => {
        setSort((current) => (current === `-${field}` ? field : `-${field}`));
        resetPage();
    };

    const submitAction = useCallback(() => {
        if (!action) return;
        setSaving(true);
        setActionError('');
        api.post(`/plugin/loan/api/requests/${action.id}/${action.type}/`, { notes })
            .then(() => {
                setAction(null);
                setNotes('');
                setReloadKey((value) => value + 1);
                onDataChanged?.();
            })
            .catch((err) => setActionError(errorText(err)))
            .finally(() => setSaving(false));
    }, [action, api, notes, onDataChanged]);

    const openAction = (request, type) => {
        setAction({ id: request.pk, type });
        setNotes('');
        setActionError('');
        setSignature('');
    };

    return h(
        M.Stack,
        { gap: 'md' },
        h(
            M.Group,
            { justify: 'space-between', align: 'center', wrap: 'wrap' },
            h(M.Title, { order: 4 }, 'Requests'),
            h(
                M.Group,
                { gap: 'sm' },
                h(
                    M.Anchor,
                    {
                        href: `/plugin/loan/api/export/requests.csv?${exportQuery}`,
                        target: '_blank',
                        size: 'sm'
                    },
                    'Export CSV'
                ),
            )
        ),
        h(TableToolbar, {
            search,
            onSearch: (value) => {
                setSearch(value);
                resetPage();
            },
            placeholder: 'Search reference, requester, part, purpose…',
            filters: [
                {
                    placeholder: 'All statuses',
                    data: REQUEST_STATUS_OPTIONS,
                    value: status || null,
                    onChange: (value) => {
                        setStatus(value || '');
                        resetPage();
                    },
                    clearable: true,
                    width: 170
                },
                {
                    placeholder: 'Any allocation',
                    data: REQUEST_ALLOCATION_OPTIONS,
                    value: allocation || null,
                    onChange: (value) => {
                        setAllocation(value || '');
                        resetPage();
                    },
                    clearable: true,
                    width: 175
                },
                {
                    placeholder: 'Sort',
                    data: REQUEST_SORT_OPTIONS,
                    value: sort,
                    onChange: (value) => {
                        setSort(value || '-created');
                        resetPage();
                    },
                    width: 165
                }
            ]
        }),
        h(ErrorAlert, { error }),
        requests && requests.length === 0 && !loading
            ? h(EmptyState, {
                  label: filterLabel(
                      hasFilters,
                      'No loan requests yet.',
                      'No requests match these filters.'
                  )
              })
            : requests
              ? h(
                    TableShell,
                    { loading },
                    h(
                        M.Table,
                        { highlightOnHover: true, verticalSpacing: 'sm', horizontalSpacing: 'md' },
                        h(
                            M.Table.Thead,
                            null,
                            h(
                                M.Table.Tr,
                                null,
                                h(SortTh, {
                                    label: 'Reference',
                                    field: 'reference',
                                    sort,
                                    onSort: toggleSort
                                }),
                                h(SortTh, {
                                    label: 'Requester',
                                    field: 'requester',
                                    sort,
                                    onSort: toggleSort
                                }),
                                h(SortTh, {
                                    label: 'Items',
                                    field: 'items',
                                    sort,
                                    onSort: toggleSort
                                }),
                                h(SortTh, {
                                    label: 'Status',
                                    field: 'status',
                                    sort,
                                    onSort: toggleSort
                                }),
                                h(M.Table.Th, null, 'Allocation'),
                                h(SortTh, {
                                    label: 'Created',
                                    field: 'created',
                                    sort,
                                    onSort: toggleSort
                                }),
                                h(M.Table.Th, null, 'Actions')
                            )
                        ),
                        h(
                            M.Table.Tbody,
                            null,
                            requests.map((request) =>
                                h(
                                    M.Table.Tr,
                                    { key: request.pk },
                                    h(
                                        M.Table.Td,
                                        null,
                                        h(
                                            M.Stack,
                                            { gap: 0 },
                                            h(
                                                M.Anchor,
                                                {
                                                    component: 'button',
                                                    type: 'button',
                                                    fw: 600,
                                                    onClick: () =>
                                                        context.navigate(
                                                            `/plugin/loan/requests/${request.pk}`
                                                        )
                                                },
                                                request.reference
                                            ),
                                            request.loan_reference
                                                ? h(
                                                      M.Text,
                                                      { size: 'xs', c: 'dimmed' },
                                                      `Loan ${request.loan_reference}`
                                                  )
                                                : null
                                        )
                                    ),
                                    h(
                                        M.Table.Td,
                                        null,
                                        h(
                                            M.Stack,
                                            { gap: 0 },
                                            h(M.Text, { size: 'sm', fw: 500 }, request.requester),
                                            request.requester_email
                                                ? h(
                                                      M.Text,
                                                      { size: 'xs', c: 'dimmed' },
                                                      request.requester_email
                                                  )
                                                : null
                                        )
                                    ),
                                    h(
                                        M.Table.Td,
                                        null,
                                        h(
                                            M.Stack,
                                            { gap: 0 },
                                            h(M.Text, { size: 'sm' }, plural(request.item_count, 'line')),
                                            h(
                                                M.Text,
                                                { size: 'xs', c: 'dimmed' },
                                                plural(request.total_quantity, 'unit')
                                            )
                                        )
                                    ),
                                    h(
                                        M.Table.Td,
                                        null,
                                        h(
                                            M.Stack,
                                            { gap: 2 },
                                            h(StatusBadge, {
                                                status: request.status,
                                                label: request.status_display
                                            }),
                                            request.loan_status
                                                ? h(
                                                      M.Text,
                                                      { size: 'xs', c: 'dimmed' },
                                                      request.loan_status_display
                                                  )
                                                : null
                                        )
                                    ),
                                    h(
                                        M.Table.Td,
                                        null,
                                        request.loan_pk
                                            ? h(
                                                  M.Badge,
                                                  { color: 'blue', variant: 'light', size: 'sm' },
                                                  'Issued'
                                              )
                                            : request.status === 'rejected' ||
                                                request.status === 'cancelled'
                                              ? h(M.Text, { size: 'xs', c: 'dimmed' }, '—')
                                              : Number(request.total_quantity) > 0
                                                ? request.is_fully_allocated
                                                    ? h(
                                                          M.Badge,
                                                          { color: 'green', variant: 'light', size: 'sm' },
                                                          'Allocated'
                                                      )
                                                    : h(
                                                          M.Badge,
                                                          { color: 'orange', variant: 'light', size: 'sm' },
                                                          `${formatQty(request.allocated_quantity)} / ${formatQty(request.total_quantity)}`
                                                      )
                                                : h(M.Text, { size: 'xs', c: 'dimmed' }, '—')
                                    ),
                                    h(M.Table.Td, null, formatDate(request.created)),
                                    h(
                                        M.Table.Td,
                                        null,
                                        h(
                                            M.Group,
                                            { gap: 'xs', wrap: 'nowrap' },
                                            h(
                                                M.Button,
                                                {
                                                    size: 'xs',
                                                    variant: 'default',
                                                    onClick: () =>
                                                        context.navigate(
                                                            `/plugin/loan/requests/${request.pk}`
                                                        )
                                                },
                                                'View'
                                            ),
                                            request.can_approve
                                                ? h(
                                                      M.Button,
                                                      {
                                                          size: 'xs',
                                                          color: 'green',
                                                          onClick: () => openAction(request, 'approve')
                                                      },
                                                      'Approve'
                                                  )
                                                : null,
                                            request.can_approve
                                                ? h(
                                                      M.Button,
                                                      {
                                                          size: 'xs',
                                                          color: 'red',
                                                          variant: 'light',
                                                          onClick: () => openAction(request, 'reject')
                                                      },
                                                      'Reject'
                                                  )
                                                : null,
                                            request.can_checkout
                                                ? h(
                                                      M.Button,
                                                      {
                                                          size: 'xs',
                                                          onClick: () => openAction(request, 'checkout')
                                                      },
                                                      'Hand out'
                                                  )
                                                : null
                                        )
                                    )
                                )
                            )
                        )
                    )
                )
              : h(Loading),
        total > 0
            ? h(TableFooter, {
                  total,
                  limit,
                  page,
                  onPage: setPage,
                  onLimit: (value) => {
                      setLimit(value);
                      resetPage();
                  },
                  label: 'requests'
              })
            : null,
        h(
            M.Modal,
            {
                opened: Boolean(action),
                onClose: () => setAction(null),
                title:
                    action?.type === 'approve'
                        ? 'Approve request'
                        : action?.type === 'reject'
                          ? 'Reject request'
                          : 'Hand out request',
                centered: true
            },
            h(
                M.Stack,
                { gap: 'sm' },
                h(M.Text, { size: 'sm', c: 'dimmed' }, action?.id ? `Request #${action.id}` : ''),
                h(M.Textarea, {
                    label: 'Notes',
                    minRows: 3,
                    value: notes,
                    onChange: (event) => setNotes(event.currentTarget.value)
                }),
                action?.type === 'checkout'
                    ? h(SignaturePad, {
                          value: signature,
                          onChange: setSignature,
                          label: 'Borrower signature',
                          required: true
                      })
                    : null,
                h(ErrorAlert, { error: actionError }),
                h(
                    M.Group,
                    { justify: 'flex-end' },
                    h(M.Button, { variant: 'default', onClick: () => setAction(null) }, 'Cancel'),
                    h(
                        M.Button,
                        {
                            color: action?.type === 'reject' ? 'red' : 'green',
                            loading: saving,
                            onClick: () => {
                                if (action?.type === 'checkout') {
                                    if (!signature) {
                                        setActionError('The borrower must sign before the items are handed out.');
                                        return;
                                    }
                                    setSaving(true);
                                    setActionError('');
                                    api.post('/plugin/loan/api/checkout/', {
                                        request_id: action.id,
                                        notes,
                                        signature
                                    })
                                        .then(() => {
                                            setAction(null);
                                            setNotes('');
                                            setReloadKey((value) => value + 1);
                                            onDataChanged?.();
                                        })
                                        .catch((err) => setActionError(errorText(err)))
                                        .finally(() => setSaving(false));
                                } else {
                                    submitAction();
                                }
                            }
                        },
                        action?.type === 'reject' ? 'Reject' : 'Confirm'
                    )
                )
            )
        )
    );
}

function LoansPanel({ context, onDataChanged }) {
    const api = context.api;
    const [reloadKey, setReloadKey] = useState(0);
    const [search, setSearch] = useState('');
    const [status, setStatus] = useState('');
    const [sort, setSort] = useState('-issued_at');
    const [page, setPage] = useState(0);
    const [limit, setLimit] = useState(25);
    const [returnLoan, setReturnLoan] = useState(null);
    const debouncedSearch = useDebounced(search);
    const query = buildQuery({
        search: debouncedSearch.trim(),
        status,
        sort,
        limit,
        offset: page * limit
    });
    const { data: loans, total, error, loading } = usePagedList(
        api,
        '/plugin/loan/api/loans/',
        query,
        reloadKey
    );
    const hasFilters = Boolean(debouncedSearch.trim() || status);
    const exportQuery = buildQuery({ search: debouncedSearch.trim(), status, sort });
    const resetPage = () => setPage(0);
    const toggleSort = (field) => {
        setSort((current) => (current === `-${field}` ? field : `-${field}`));
        resetPage();
    };

    return h(
        M.Stack,
        { gap: 'md' },
        h(
            M.Group,
            { justify: 'space-between', align: 'center', wrap: 'wrap' },
            h(M.Title, { order: 4 }, 'Loans'),
            h(
                M.Group,
                { gap: 'sm' },
                h(
                    M.Anchor,
                    {
                        href: `/plugin/loan/api/export/loans.csv?${exportQuery}`,
                        target: '_blank',
                        size: 'sm'
                    },
                    'Export CSV'
                ),
            )
        ),
        h(TableToolbar, {
            search,
            onSearch: (value) => {
                setSearch(value);
                resetPage();
            },
            placeholder: 'Search reference, borrower, part, notes…',
            filters: [
                {
                    placeholder: 'All loans',
                    data: LOAN_STATUS_OPTIONS,
                    value: status || null,
                    onChange: (value) => {
                        setStatus(value || '');
                        resetPage();
                    },
                    clearable: true,
                    width: 165
                },
                {
                    placeholder: 'Sort',
                    data: LOAN_SORT_OPTIONS,
                    value: sort,
                    onChange: (value) => {
                        setSort(value || '-issued_at');
                        resetPage();
                    },
                    width: 165
                }
            ]
        }),
        h(ErrorAlert, { error }),
        loans && loans.length === 0 && !loading
            ? h(EmptyState, {
                  label: filterLabel(
                      hasFilters,
                      'No loans have been issued yet.',
                      'No loans match these filters.'
                  )
              })
            : loans
              ? h(
                    TableShell,
                    { loading },
                    h(
                        M.Table,
                        { highlightOnHover: true, verticalSpacing: 'sm', horizontalSpacing: 'md' },
                        h(
                            M.Table.Thead,
                            null,
                            h(
                                M.Table.Tr,
                                null,
                                h(SortTh, {
                                    label: 'Reference',
                                    field: 'reference',
                                    sort,
                                    onSort: toggleSort
                                }),
                                h(SortTh, {
                                    label: 'Borrower',
                                    field: 'borrower',
                                    sort,
                                    onSort: toggleSort
                                }),
                                h(SortTh, {
                                    label: 'Items',
                                    field: 'items',
                                    sort,
                                    onSort: toggleSort
                                }),
                                h(SortTh, {
                                    label: 'Issued',
                                    field: 'issued_at',
                                    sort,
                                    onSort: toggleSort
                                }),
                                h(SortTh, {
                                    label: 'Due',
                                    field: 'due_at',
                                    sort,
                                    onSort: toggleSort
                                }),
                                h(SortTh, {
                                    label: 'Status',
                                    field: 'status',
                                    sort,
                                    onSort: toggleSort
                                }),
                                h(M.Table.Th, null, 'Actions')
                            )
                        ),
                        h(
                            M.Table.Tbody,
                            null,
                            loans.map((loan) =>
                                h(
                                    M.Table.Tr,
                                    { key: loan.pk },
                                    h(
                                        M.Table.Td,
                                        null,
                                        h(
                                            M.Stack,
                                            { gap: 0 },
                                            loan.request_pk
                                                ? h(
                                                      M.Anchor,
                                                      {
                                                          component: 'button',
                                                          type: 'button',
                                                          fw: 600,
                                                          onClick: () =>
                                                              context.navigate(
                                                                  `/plugin/loan/requests/${loan.request_pk}`
                                                              )
                                                      },
                                                      loan.reference
                                                  )
                                                : h(M.Text, { fw: 600 }, loan.reference),
                                            loan.request_reference
                                                ? h(
                                                      M.Text,
                                                      { size: 'xs', c: 'dimmed' },
                                                      loan.request_reference
                                                  )
                                                : null
                                        )
                                    ),
                                    h(
                                        M.Table.Td,
                                        null,
                                        h(
                                            M.Stack,
                                            { gap: 0 },
                                            h(M.Text, { size: 'sm', fw: 500 }, loan.borrower),
                                            loan.borrower_email
                                                ? h(
                                                      M.Text,
                                                      { size: 'xs', c: 'dimmed' },
                                                      loan.borrower_email
                                                  )
                                                : null
                                        )
                                    ),
                                    h(
                                        M.Table.Td,
                                        null,
                                        h(
                                            M.Stack,
                                            { gap: 0 },
                                            h(M.Text, { size: 'sm' }, plural(loan.item_count, 'line')),
                                            h(
                                                M.Text,
                                                { size: 'xs', c: 'dimmed' },
                                                `${formatQty(loan.remaining_quantity)} of ${formatQty(loan.total_quantity)} out`
                                            )
                                        )
                                    ),
                                    h(M.Table.Td, null, formatDate(loan.issued_at)),
                                    h(
                                        M.Table.Td,
                                        null,
                                        h(
                                            M.Stack,
                                            { gap: 0 },
                                            h(
                                                M.Text,
                                                {
                                                    size: 'sm',
                                                    c: loan.is_overdue ? 'red' : undefined,
                                                    fw: loan.is_overdue ? 600 : undefined
                                                },
                                                formatDate(loan.due_at)
                                            ),
                                            loan.is_overdue
                                                ? h(
                                                      M.Text,
                                                      { size: 'xs', c: 'red' },
                                                      `${loan.days_overdue} day${loan.days_overdue === 1 ? '' : 's'} overdue`
                                                  )
                                                : null
                                        )
                                    ),
                                    h(
                                        M.Table.Td,
                                        null,
                                        h(
                                            M.Stack,
                                            { gap: 2 },
                                            h(StatusBadge, {
                                                status: loan.status,
                                                label: loan.status_display
                                            }),
                                            loan.renewals
                                                ? h(
                                                      M.Text,
                                                      { size: 'xs', c: 'dimmed' },
                                                      `${loan.renewals} renewal${loan.renewals === 1 ? '' : 's'}`
                                                  )
                                                : null
                                        )
                                    ),
                                    h(
                                        M.Table.Td,
                                        null,
                                        h(
                                            M.Group,
                                            { gap: 'xs', wrap: 'nowrap' },
                                            loan.can_return
                                                ? h(
                                                      M.Button,
                                                      {
                                                          size: 'xs',
                                                          onClick: () => setReturnLoan(loan)
                                                      },
                                                      'Return'
                                                  )
                                                : null,
                                            h(
                                                M.Menu,
                                                { position: 'bottom-end', shadow: 'md' },
                                                h(
                                                    M.Menu.Target,
                                                    null,
                                                    h(
                                                        M.Button,
                                                        { size: 'xs', variant: 'default' },
                                                        'More'
                                                    )
                                                ),
                                                h(
                                                    M.Menu.Dropdown,
                                                    null,
                                                    h(
                                                        M.Menu.Item,
                                                        {
                                                            component: 'a',
                                                            href: loan.handout_receipt_url,
                                                            target: '_blank'
                                                        },
                                                        'Handout receipt'
                                                    ),
                                                    loan.status === 'returned'
                                                        ? h(
                                                              M.Menu.Item,
                                                              {
                                                                  component: 'a',
                                                                  href: loan.return_receipt_url,
                                                                  target: '_blank'
                                                              },
                                                              'Return receipt'
                                                          )
                                                        : null,
                                                    loan.request_pk
                                                        ? h(
                                                              M.Menu.Item,
                                                              {
                                                                  onClick: () =>
                                                                      context.navigate(
                                                                          `/plugin/loan/requests/${loan.request_pk}`
                                                                      )
                                                              },
                                                              'Open request'
                                                          )
                                                        : null
                                                )
                                            )
                                        )
                                    )
                                )
                            )
                        )
                    )
                )
              : h(Loading),
        total > 0
            ? h(TableFooter, {
                  total,
                  limit,
                  page,
                  onPage: setPage,
                  onLimit: (value) => {
                      setLimit(value);
                      resetPage();
                  },
                  label: 'loans'
              })
            : null,
        h(ReturnModal, {
            context,
            loan: returnLoan,
            onClose: () => setReturnLoan(null),
            onSaved: () => {
                setReturnLoan(null);
                setReloadKey((value) => value + 1);
                onDataChanged?.();
            }
        })
    );
}

function ReturnModal({ context, loan, onClose, onSaved }) {
    const api = context.api;
    const [detail, setDetail] = useState(null);
    const [error, setError] = useState('');
    const [saving, setSaving] = useState(false);
    const [quantities, setQuantities] = useState({});
    const [conditions, setConditions] = useState({});
    const [notes, setNotes] = useState('');
    const [signature, setSignature] = useState('');
    const [scanValue, setScanValue] = useState('');
    const [scanBusy, setScanBusy] = useState(false);
    const [scanNote, setScanNote] = useState('');

    useEffect(() => {
        if (!loan) {
            setDetail(null);
            setQuantities({});
            setConditions({});
            setSignature('');
            setScanValue('');
            setScanBusy(false);
            setScanNote('');
            setError('');
            return;
        }
        let active = true;
        setError('');
        api.get(`/plugin/loan/api/loans/${loan.pk}/`)
            .then((response) => {
                if (!active) return;
                const data = response.data;
                setDetail(data);
                const qty = {};
                const cond = {};
                (data.items || []).forEach((item) => {
                    if (item.lost || Number(item.remaining_quantity) <= 0) return;
                    qty[item.pk] = 0;
                    cond[item.pk] = 'good';
                });
                setQuantities(qty);
                setConditions(cond);
                setScanValue('');
                setScanNote('');
                setScanBusy(false);
            })
            .catch((err) => {
                if (active) setError(errorText(err));
            });
        return () => {
            active = false;
        };
    }, [api, loan]);

    const items = (detail?.items || []).filter(
        (item) => !item.lost && Number(item.remaining_quantity) > 0
    );
    const expectedUnits = items.reduce(
        (total, item) => total + Number(item.remaining_quantity || 0),
        0
    );
    const countedUnits = items.reduce(
        (total, item) =>
            total +
            Math.min(
                Number(quantities[item.pk] || 0),
                Number(item.remaining_quantity || 0)
            ),
        0
    );
    const countedLines = items.filter(
        (item) => Number(quantities[item.pk] || 0) > 0
    ).length;
    const progress = expectedUnits
        ? Math.round((countedUnits / expectedUnits) * 100)
        : 100;

    const countItem = (item, quantity) => {
        setQuantities((current) => ({
            ...current,
            [item.pk]: Math.min(
                Math.max(Number(quantity) || 0, 0),
                Number(item.remaining_quantity) || 0
            )
        }));
    };

    const countAll = () => {
        const next = {};
        items.forEach((item) => {
            next[item.pk] = Number(item.remaining_quantity) || 0;
        });
        setQuantities(next);
        setScanNote('All outstanding units counted.');
    };

    const resetCounts = () => {
        const next = {};
        items.forEach((item) => {
            next[item.pk] = 0;
        });
        setQuantities(next);
        setScanNote('');
        setError('');
    };

    const scanReturn = (barcode) => {
        const value = (barcode || '').trim();
        if (!detail || !value) return;
        setScanBusy(true);
        setScanNote('');
        setError('');
        api.post('/plugin/loan/api/scan/', { barcode: value })
            .then((response) => {
                const found = response.data || {};
                if (!found.success) {
                    setError(found.error || 'No matching stock item found.');
                    return;
                }
                if (found.type !== 'stockitem') {
                    setError('Scan a stock item barcode or QR code.');
                    return;
                }
                const item = items.find(
                    (entry) => String(entry.stock_item) === String(found.data.pk)
                );
                if (!item) {
                    setError(`That stock item is not on loan ${detail.reference}.`);
                    return;
                }
                const remaining = Number(item.remaining_quantity) || 0;
                const current = Number(quantities[item.pk] || 0);
                if (remaining <= 0) {
                    setError('That item has already been returned.');
                    return;
                }
                if (current >= remaining) {
                    setError(`${item.part_name} is already fully counted.`);
                    return;
                }
                const increment = found.data.serial ? 1 : remaining;
                const next = Math.min(remaining, current + increment);
                countItem(item, next);
                setScanValue('');
                setScanNote(
                    `${item.part_name} counted (${next} of ${remaining}${
                        found.data.serial ? '' : ' units'
                    }).`
                );
            })
            .catch((err) => setError(errorText(err)))
            .finally(() => setScanBusy(false));
    };

    const submit = () => {
        if (!detail) return;
        const lines = items
            .map((item) => ({
                item_id: item.pk,
                quantity: Number(quantities[item.pk] || 0),
                condition: conditions[item.pk] || 'good'
            }))
            .filter((line) => line.quantity > 0);
        if (!lines.length) {
            setError('Enter at least one return quantity.');
            return;
        }
        if (!signature) {
            setError('The borrower must sign before the return is recorded.');
            return;
        }
        setSaving(true);
        setError('');
        api.post(`/plugin/loan/api/loans/${detail.pk}/return/`, {
            lines,
            notes,
            signature
        })
            .then(() => onSaved())
            .catch((err) => setError(errorText(err)))
            .finally(() => setSaving(false));
    };

    return h(
        M.Modal,
        {
            opened: Boolean(loan),
            onClose,
            title: loan ? `Return ${loan.reference}` : 'Return',
            size: 'xl',
            centered: true
        },
        h(
            M.Stack,
            { gap: 'sm' },
            detail ? null : h(Loading),
            h(ErrorAlert, { error }),
            detail && items.length > 0
                ? h(
                      M.Paper,
                      { withBorder: true, p: 'sm' },
                      h(
                          M.Stack,
                          { gap: 'xs' },
                          h(
                              M.Group,
                              { align: 'flex-end', wrap: 'wrap' },
                              h(M.TextInput, {
                                  label: 'Scan to count',
                                  placeholder: 'Scan a stock item barcode or QR code',
                                  value: scanValue,
                                  onChange: (event) =>
                                      setScanValue(event.currentTarget.value),
                                  onKeyDown: (event) => {
                                      if (event.key === 'Enter') {
                                          event.preventDefault();
                                          scanReturn(scanValue);
                                      }
                                  },
                                  style: { flex: '1 1 320px' },
                                  description:
                                      'Scan a serial to count one unit. Scanning a bulk item counts its full outstanding quantity.'
                              }),
                              h(
                                  M.Button,
                                  {
                                      variant: 'default',
                                      loading: scanBusy,
                                      onClick: () => scanReturn(scanValue)
                                  },
                                  'Count'
                              ),
                              h(M.Button, { variant: 'light', onClick: countAll }, 'Count all'),
                              h(
                                  M.Button,
                                  { variant: 'subtle', color: 'gray', onClick: resetCounts },
                                  'Reset'
                              )
                          ),
                          h(M.Progress, {
                              value: progress,
                              color: progress === 100 ? 'green' : 'blue',
                              size: 'sm',
                              'aria-label': `Counted ${countedUnits} of ${expectedUnits} units`
                          }),
                          h(
                              M.Group,
                              { justify: 'space-between', wrap: 'wrap' },
                              h(
                                  M.Text,
                                  { size: 'sm', c: 'dimmed' },
                                  `Counted ${countedUnits} of ${expectedUnits} units · ${countedLines} of ${items.length} lines`
                              ),
                              scanNote
                                  ? h(
                                        M.Text,
                                        { size: 'sm', c: 'green', fw: 500 },
                                        scanNote
                                    )
                                  : null
                          )
                      )
                  )
                : null,
            items.length > 0
                ? h(
                      'div',
                      { style: { overflowX: 'auto' } },
                      h(
                          M.Table,
                          { verticalSpacing: 'xs' },
                          h(
                              M.Table.Thead,
                              null,
                              h(
                                  M.Table.Tr,
                                  null,
                                  h(M.Table.Th, null, 'Part'),
                                  h(M.Table.Th, null, 'Asset'),
                                  h(M.Table.Th, null, 'Out'),
                                  h(M.Table.Th, null, 'Return qty'),
                                  h(M.Table.Th, null, 'Condition')
                              )
                          ),
                          h(
                              M.Table.Tbody,
                              null,
                              items.map((item) =>
                                  h(
                                      M.Table.Tr,
                                      { key: item.pk },
                                      h(
                                          M.Table.Td,
                                          null,
                                          h(
                                              M.Group,
                                              { gap: 6, wrap: 'nowrap' },
                                              h(M.Text, { size: 'sm' }, item.part_name),
                                              Number(quantities[item.pk] || 0) >=
                                                  Number(item.remaining_quantity)
                                                  ? h(
                                                        M.Text,
                                                        {
                                                            size: 'sm',
                                                            c: 'green',
                                                            fw: 700,
                                                            title: 'Counted',
                                                            'aria-label': 'Counted'
                                                        },
                                                        '✓'
                                                    )
                                                  : null
                                          )
                                      ),
                                      h(M.Table.Td, null, item.stock_item_label),
                                      h(M.Table.Td, null, item.remaining_quantity),
                                      h(
                                          M.Table.Td,
                                          null,
                                          h(M.NumberInput, {
                                              size: 'xs',
                                              min: 0,
                                              max: Number(item.remaining_quantity),
                                              value: quantities[item.pk] || 0,
                                              onChange: (value) =>
                                                  setQuantities((current) => ({
                                                      ...current,
                                                      [item.pk]: value
                                                  }))
                                          })
                                      ),
                                      h(
                                          M.Table.Td,
                                          null,
                                          h(M.Select, {
                                              size: 'xs',
                                              value: conditions[item.pk] || 'good',
                                              onChange: (value) =>
                                                  setConditions((current) => ({
                                                      ...current,
                                                      [item.pk]: value
                                                  })),
                                              data: [
                                                  { value: 'good', label: 'Good' },
                                                  { value: 'damaged', label: 'Damaged' },
                                                  { value: 'incomplete', label: 'Incomplete' },
                                                  { value: 'other', label: 'Other' }
                                              ]
                                          })
                                      )
                                  )
                              )
                          )
                      )
                  )
                : h(M.Text, { c: 'dimmed' }, 'All items on this loan have already been returned.'),
            h(SignaturePad, {
                value: signature,
                onChange: setSignature,
                label: 'Borrower signature',
                required: true
            }),
            h(M.Textarea, {
                label: 'Return notes',
                minRows: 2,
                value: notes,
                onChange: (event) => setNotes(event.currentTarget.value)
            }),
            h(
                M.Group,
                { justify: 'flex-end' },
                h(M.Button, { variant: 'default', onClick: onClose }, 'Cancel'),
                h(M.Button, { loading: saving, disabled: !items.length, onClick: submit }, 'Confirm return')
            )
        )
    );
}

function HandoutPanel({ context, onDataChanged }) {
    const api = context.api;
    const [search, setSearch] = useState('');
    const [allocation, setAllocation] = useState('');
    const [sort, setSort] = useState('needed_by');
    const [page, setPage] = useState(0);
    const [limit, setLimit] = useState(25);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(null);
    const [result, setResult] = useState(null);
    const [reloadKey, setReloadKey] = useState(0);
    const [handoutId, setHandoutId] = useState(null);
    const debouncedSearch = useDebounced(search);
    const query = buildQuery({
        status: 'approved',
        search: debouncedSearch.trim(),
        allocation,
        sort,
        limit,
        offset: page * limit
    });
    const {
        data: requests,
        total,
        error: listError,
        loading
    } = usePagedList(api, '/plugin/loan/api/requests/', query, reloadKey);
    const hasFilters = Boolean(debouncedSearch.trim() || allocation);
    const resetPage = () => setPage(0);
    const toggleSort = (field) => {
        setSort((current) => (current === `-${field}` ? field : `-${field}`));
        resetPage();
    };

    const handout = (requestId, signature) => {
        setBusy(requestId);
        setError('');
        setResult(null);
        return api.post('/plugin/loan/api/checkout/', {
            request_id: requestId,
            signature
        })
            .then((response) => {
                setResult(response.data);
                setReloadKey((value) => value + 1);
                setHandoutId(null);
                onDataChanged?.();
            })
            .catch((err) => {
                setError(errorText(err));
                throw err;
            })
            .finally(() => setBusy(null));
    };

    return h(
        M.Stack,
        { gap: 'md' },
        h(
            M.Group,
            { justify: 'space-between', align: 'center', wrap: 'wrap' },
            h(M.Title, { order: 4 }, 'Hand out'),
            h(
                M.Anchor,
                { href: context.context?.request_url, target: '_blank', size: 'sm' },
                'Create a request'
            )
        ),
        result
            ? h(
                  M.Alert,
                  { color: 'green', title: `Loan ${result.reference} issued` },
                  h(
                      M.Group,
                      { gap: 'sm' },
                      h(
                          M.Anchor,
                          {
                              href: `/plugin/loan/loans/${result.pk}/receipt/?type=handout`,
                              target: '_blank'
                          },
                          'Print handout receipt'
                      ),
                      h(M.Anchor, { href: result.qr_url, target: '_blank' }, 'Open QR')
                  )
              )
            : null,
        h(TableToolbar, {
            search,
            onSearch: (value) => {
                setSearch(value);
                resetPage();
            },
            placeholder: 'Search approved requests…',
            filters: [
                {
                    placeholder: 'Any allocation',
                    data: REQUEST_ALLOCATION_OPTIONS,
                    value: allocation || null,
                    onChange: (value) => {
                        setAllocation(value || '');
                        resetPage();
                    },
                    clearable: true,
                    width: 175
                },
                {
                    placeholder: 'Sort',
                    data: REQUEST_SORT_OPTIONS,
                    value: sort,
                    onChange: (value) => {
                        setSort(value || 'needed_by');
                        resetPage();
                    },
                    width: 165
                }
            ]
        }),
        h(ErrorAlert, { error }),
        h(ErrorAlert, { error: listError }),
        requests && requests.length === 0 && !loading
            ? h(EmptyState, {
                  label: filterLabel(
                      hasFilters,
                      'No approved requests are waiting for handout.',
                      'No approved requests match these filters.'
                  )
              })
            : requests
              ? h(
                    TableShell,
                    { loading },
                    h(
                        M.Table,
                        { highlightOnHover: true, verticalSpacing: 'sm', horizontalSpacing: 'md' },
                        h(
                            M.Table.Thead,
                            null,
                            h(
                                M.Table.Tr,
                                null,
                                h(SortTh, {
                                    label: 'Reference',
                                    field: 'reference',
                                    sort,
                                    onSort: toggleSort
                                }),
                                h(SortTh, {
                                    label: 'Requester',
                                    field: 'requester',
                                    sort,
                                    onSort: toggleSort
                                }),
                                h(SortTh, {
                                    label: 'Items',
                                    field: 'items',
                                    sort,
                                    onSort: toggleSort
                                }),
                                h(M.Table.Th, null, 'Allocation'),
                                h(SortTh, {
                                    label: 'Pickup',
                                    field: 'needed_by',
                                    sort,
                                    onSort: toggleSort
                                }),
                                h(SortTh, {
                                    label: 'Return by',
                                    field: 'return_by',
                                    sort,
                                    onSort: toggleSort
                                }),
                                h(M.Table.Th, null, 'Actions')
                            )
                        ),
                        h(
                            M.Table.Tbody,
                            null,
                            requests.map((request) =>
                                h(
                                    M.Table.Tr,
                                    { key: request.pk },
                                    h(
                                        M.Table.Td,
                                        null,
                                        h(
                                            M.Stack,
                                            { gap: 0 },
                                            h(
                                                M.Anchor,
                                                {
                                                    component: 'button',
                                                    type: 'button',
                                                    fw: 600,
                                                    onClick: () =>
                                                        context.navigate(
                                                            `/plugin/loan/requests/${request.pk}`
                                                        )
                                                },
                                                request.reference
                                            ),
                                            request.requester_organization
                                                ? h(
                                                      M.Text,
                                                      { size: 'xs', c: 'dimmed' },
                                                      request.requester_organization
                                                  )
                                                : null
                                        )
                                    ),
                                    h(
                                        M.Table.Td,
                                        null,
                                        h(
                                            M.Stack,
                                            { gap: 0 },
                                            h(M.Text, { size: 'sm', fw: 500 }, request.requester),
                                            request.requester_email
                                                ? h(
                                                      M.Text,
                                                      { size: 'xs', c: 'dimmed' },
                                                      request.requester_email
                                                  )
                                                : null
                                        )
                                    ),
                                    h(
                                        M.Table.Td,
                                        null,
                                        h(
                                            M.Stack,
                                            { gap: 0 },
                                            h(M.Text, { size: 'sm' }, plural(request.item_count, 'line')),
                                            h(
                                                M.Text,
                                                { size: 'xs', c: 'dimmed' },
                                                plural(request.total_quantity, 'unit')
                                            )
                                        )
                                    ),
                                    h(
                                        M.Table.Td,
                                        null,
                                        request.is_fully_allocated
                                            ? h(
                                                  M.Badge,
                                                  { color: 'green', variant: 'light', size: 'sm' },
                                                  'Allocated'
                                              )
                                            : h(
                                                  M.Badge,
                                                  { color: 'orange', variant: 'light', size: 'sm' },
                                                  `${formatQty(request.allocated_quantity)} / ${formatQty(request.total_quantity)}`
                                              )
                                    ),
                                    h(M.Table.Td, null, formatDate(request.needed_by)),
                                    h(M.Table.Td, null, formatDate(request.return_by)),
                                    h(
                                        M.Table.Td,
                                        null,
                                        h(
                                            M.Group,
                                            { gap: 'xs', wrap: 'nowrap' },
                                            h(
                                                M.Button,
                                                {
                                                    size: 'xs',
                                                    variant: 'default',
                                                    onClick: () =>
                                                        context.navigate(
                                                            `/plugin/loan/requests/${request.pk}`
                                                        )
                                                },
                                                'View'
                                            ),
                                            h(
                                                M.Button,
                                                {
                                                    size: 'xs',
                                                    loading: busy === request.pk,
                                                    onClick: () => setHandoutId(request.pk)
                                                },
                                                'Hand out'
                                            )
                                        )
                                    )
                                )
                            )
                        )
                    )
                )
              : h(Loading),
        total > 0
            ? h(TableFooter, {
                  total,
                  limit,
                  page,
                  onPage: setPage,
                  onLimit: (value) => {
                      setLimit(value);
                      resetPage();
                  },
                  label: 'ready requests'
              })
            : null,
        h(RequestDetailModal, {
            context,
            requestId: handoutId,
            handoutMode: true,
            onClose: () => setHandoutId(null),
            onHandout: handout
        })
    );
}

function StaffPanel({ context }) {
    const api = context.api;
    const [reloadKey, setReloadKey] = useState(0);
    const [search, setSearch] = useState('');
    const [roleFilter, setRoleFilter] = useState('');
    const [activeFilter, setActiveFilter] = useState('');
    const [page, setPage] = useState(0);
    const [limit, setLimit] = useState(25);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const [userQuery, setUserQuery] = useState('');
    const [userOptions, setUserOptions] = useState([]);
    const [selectedUserId, setSelectedUserId] = useState(null);
    const [userSearchLoading, setUserSearchLoading] = useState(false);
    const [newRole, setNewRole] = useState('approver');
    const debouncedSearch = useDebounced(search);
    const debouncedUserQuery = useDebounced(userQuery, 250);
    const query = buildQuery({
        search: debouncedSearch.trim(),
        role: roleFilter,
        active: activeFilter,
        limit,
        offset: page * limit
    });
    const {
        data: staff,
        total,
        error: listError,
        loading
    } = usePagedList(api, '/plugin/loan/api/staff/', query, reloadKey);
    const hasFilters = Boolean(debouncedSearch.trim() || roleFilter || activeFilter);
    const resetPage = () => setPage(0);

    useEffect(() => {
        if (selectedUserId) {
            setUserOptions([]);
            setUserSearchLoading(false);
            return undefined;
        }
        const term = debouncedUserQuery.trim();
        if (term.length < 2) {
            setUserOptions([]);
            return undefined;
        }
        let active = true;
        setUserSearchLoading(true);
        api.get('/plugin/loan/api/user-search/', { params: { search: term } })
            .then((response) => {
                if (!active) return;
                setUserOptions(
                    (response.data?.results || []).map((user) => ({
                        value: String(user.pk),
                        label: `${user.name} (@${user.username})${
                            user.email ? ` · ${user.email}` : ''
                        }`
                    }))
                );
            })
            .catch(() => {
                if (active) setUserOptions([]);
            })
            .finally(() => {
                if (active) setUserSearchLoading(false);
            });
        return () => {
            active = false;
        };
    }, [api, debouncedUserQuery, selectedUserId]);

    const add = () => {
        if (!selectedUserId) {
            setError('Search for a user and select them from the results.');
            return;
        }
        setBusy(true);
        setError('');
        api.post('/plugin/loan/api/staff/', {
            user_id: Number(selectedUserId),
            role: newRole,
            active: true
        })
            .then(() => {
                setUserQuery('');
                setUserOptions([]);
                setSelectedUserId(null);
                setReloadKey((value) => value + 1);
            })
            .catch((err) => setError(errorText(err)))
            .finally(() => setBusy(false));
    };

    const toggle = (item) => {
        setError('');
        api.patch(`/plugin/loan/api/staff/${item.pk}/`, { active: !item.active })
            .then(() => setReloadKey((value) => value + 1))
            .catch((err) => setError(errorText(err)));
    };

    const remove = (item) => {
        if (!window.confirm(`Remove the loan role for ${item.username}?`)) return;
        setError('');
        api.delete(`/plugin/loan/api/staff/${item.pk}/`)
            .then(() => setReloadKey((value) => value + 1))
            .catch((err) => setError(errorText(err)));
    };

    return h(
        M.Stack,
        { gap: 'md' },
        h(M.Title, { order: 4 }, 'Loan staff'),
        h(
            M.Paper,
            { withBorder: true, p: 'md' },
            h(
                M.Stack,
                { gap: 'sm' },
                h(M.Text, { fw: 600 }, 'Grant a loan role'),
                h(
                    M.Text,
                    { size: 'sm', c: 'dimmed' },
                    'Search by name, username or email instead of typing the exact username.'
                ),
                h(
                    M.Group,
                    { align: 'flex-start', wrap: 'wrap' },
                    h(
                        M.Stack,
                        { gap: 4, style: { flex: '1 1 340px', minWidth: 260 } },
                        h(M.TextInput, {
                            label: 'Find user',
                            placeholder: 'Search by name, username or email…',
                            value: userQuery,
                            onChange: (event) => {
                                setUserQuery(event.currentTarget.value);
                                setSelectedUserId(null);
                                setUserOptions([]);
                            },
                            leftSection: h(M.Text, { size: 'sm', c: 'dimmed' }, '⌕'),
                            rightSection: userSearchLoading
                                ? h(M.Loader, { size: 'xs' })
                                : undefined
                        }),
                        userOptions.length
                            ? h(
                                  M.Paper,
                                  {
                                      withBorder: true,
                                      p: 4,
                                      style: { maxHeight: 220, overflowY: 'auto' }
                                  },
                                  h(
                                      M.Stack,
                                      { gap: 0 },
                                      userOptions.map((user) =>
                                          h(
                                              M.Button,
                                              {
                                                  key: user.value,
                                                  variant: 'subtle',
                                                  color: 'gray',
                                                  size: 'compact-sm',
                                                  fullWidth: true,
                                                  justify: 'flex-start',
                                                  onClick: () => {
                                                      setSelectedUserId(user.value);
                                                      setUserQuery(user.label);
                                                      setUserOptions([]);
                                                  }
                                              },
                                              user.label
                                          )
                                      )
                                  )
                              )
                            : userQuery.trim().length >= 2 &&
                                !userSearchLoading &&
                                !selectedUserId
                              ? h(
                                    M.Text,
                                    { size: 'xs', c: 'dimmed', px: 4 },
                                    'No matching users'
                                )
                              : null
                    ),
                    h(M.Select, {
                        label: 'Role',
                        data: STAFF_ROLE_OPTIONS,
                        value: newRole,
                        onChange: (value) => setNewRole(value || 'approver'),
                        allowDeselect: false,
                        w: 200
                    }),
                    h(M.Button, { loading: busy, onClick: add, mt: 24 }, 'Add or update')
                ),
                h(ErrorAlert, { error })
            )
        ),
        h(TableToolbar, {
            search,
            onSearch: (value) => {
                setSearch(value);
                resetPage();
            },
            placeholder: 'Search staff by name, username or email…',
            filters: [
                {
                    placeholder: 'All roles',
                    data: STAFF_ROLE_OPTIONS,
                    value: roleFilter || null,
                    onChange: (value) => {
                        setRoleFilter(value || '');
                        resetPage();
                    },
                    clearable: true,
                    width: 180
                },
                {
                    placeholder: 'Any status',
                    data: [
                        { value: '1', label: 'Active' },
                        { value: '0', label: 'Inactive' }
                    ],
                    value: activeFilter || null,
                    onChange: (value) => {
                        setActiveFilter(value || '');
                        resetPage();
                    },
                    clearable: true,
                    width: 150
                }
            ]
        }),
        h(ErrorAlert, { error: listError }),
        staff && staff.length === 0 && !loading
            ? h(EmptyState, {
                  label: filterLabel(
                      hasFilters,
                      'No loan staff have been granted a role yet.',
                      'No staff match these filters.'
                  )
              })
            : staff
              ? h(
                    TableShell,
                    { loading },
                    h(
                        M.Table,
                        { highlightOnHover: true, verticalSpacing: 'sm', horizontalSpacing: 'md' },
                        h(
                            M.Table.Thead,
                            null,
                            h(
                                M.Table.Tr,
                                null,
                                h(M.Table.Th, null, 'User'),
                                h(M.Table.Th, null, 'Role'),
                                h(M.Table.Th, null, 'Status'),
                                h(M.Table.Th, null, 'Granted by'),
                                h(M.Table.Th, null, 'Actions')
                            )
                        ),
                        h(
                            M.Table.Tbody,
                            null,
                            staff.map((item) =>
                                h(
                                    M.Table.Tr,
                                    { key: item.pk },
                                    h(
                                        M.Table.Td,
                                        null,
                                        h(
                                            M.Stack,
                                            { gap: 0 },
                                            h(M.Text, { size: 'sm', fw: 500 }, item.name),
                                            h(
                                                M.Text,
                                                { size: 'xs', c: 'dimmed' },
                                                `@${item.username}`
                                            )
                                        )
                                    ),
                                    h(
                                        M.Table.Td,
                                        null,
                                        h(
                                            M.Badge,
                                            { color: 'blue', variant: 'light', size: 'sm' },
                                            item.role_display
                                        )
                                    ),
                                    h(
                                        M.Table.Td,
                                        null,
                                        h(
                                            M.Badge,
                                            {
                                                color: item.active ? 'green' : 'gray',
                                                variant: 'light',
                                                size: 'sm'
                                            },
                                            item.active ? 'Active' : 'Inactive'
                                        )
                                    ),
                                    h(M.Table.Td, null, item.created_by || '—'),
                                    h(
                                        M.Table.Td,
                                        null,
                                        h(
                                            M.Group,
                                            { gap: 'xs', wrap: 'nowrap' },
                                            h(
                                                M.Button,
                                                {
                                                    size: 'xs',
                                                    variant: 'default',
                                                    onClick: () => toggle(item)
                                                },
                                                item.active ? 'Deactivate' : 'Activate'
                                            ),
                                            h(
                                                M.Button,
                                                {
                                                    size: 'xs',
                                                    color: 'red',
                                                    variant: 'light',
                                                    onClick: () => remove(item)
                                                },
                                                'Remove'
                                            )
                                        )
                                    )
                                )
                            )
                        )
                    )
                )
              : h(Loading),
        total > 0
            ? h(TableFooter, {
                  total,
                  limit,
                  page,
                  onPage: setPage,
                  onLimit: (value) => {
                      setLimit(value);
                      resetPage();
                  },
                  label: 'staff'
              })
            : null
    );
}

function SetupPanel({ context }) {
    const api = context.api;
    const [data, setData] = useState(context.context || null);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);

    const load = () => {
        api.get('/plugin/loan/api/setup/')
            .then((response) => setData(response.data))
            .catch((err) => setError(errorText(err)));
    };

    useEffect(load, [api]);

    const runSetup = () => {
        setBusy(true);
        setError('');
        api.post('/plugin/loan/api/setup/', {})
            .then((response) => setData(response.data))
            .catch((err) => setError(errorText(err)))
            .finally(() => setBusy(false));
    };

    return h(
        M.Stack,
        { gap: 'md' },
        h(M.Title, { order: 4 }, 'Setup'),
        h(ErrorAlert, { error }),
        h(
            M.Paper,
            { withBorder: true, p: 'md' },
            h(
                M.Stack,
                { gap: 'xs' },
                h(
                    M.Group,
                    { justify: 'space-between' },
                    h(M.Text, { fw: 600 }, 'On Loan location'),
                    h(M.Code, null, data?.location || 'Not configured')
                ),
                h(
                    M.Group,
                    { justify: 'space-between' },
                    h(M.Text, { fw: 600 }, 'On Loan status'),
                    h(M.Code, null, data?.status || 'Not configured')
                ),
                h(
                    M.Group,
                    { justify: 'space-between' },
                    h(M.Text, { fw: 600 }, 'Configured'),
                    h(
                        M.Badge,
                        { color: data?.configured ? 'green' : 'red', variant: 'light' },
                        data?.configured ? 'Ready' : 'Incomplete'
                    )
                ),
                h(
                    M.Group,
                    { justify: 'flex-end' },
                    h(M.Button, { loading: busy, onClick: runSetup }, 'Run setup')
                )
            )
        )
    );
}

function HistoryPanel({ context }) {
    const api = context.api;
    const [search, setSearch] = useState('');
    const [eventType, setEventType] = useState('');
    const [page, setPage] = useState(0);
    const [limit, setLimit] = useState(50);
    const debouncedSearch = useDebounced(search);
    const query = buildQuery({
        search: debouncedSearch.trim(),
        event_type: eventType,
        limit,
        offset: page * limit
    });
    const {
        data: events,
        total,
        error,
        loading
    } = usePagedList(api, '/plugin/loan/api/events/', query, 0);
    const hasFilters = Boolean(debouncedSearch.trim() || eventType);
    const resetPage = () => setPage(0);

    return h(
        M.Stack,
        { gap: 'md' },
        h(M.Title, { order: 4 }, 'History'),
        h(TableToolbar, {
            search,
            onSearch: (value) => {
                setSearch(value);
                resetPage();
            },
            placeholder: 'Search notes, actor, reference…',
            filters: [
                {
                    placeholder: 'All events',
                    data: EVENT_TYPE_OPTIONS,
                    value: eventType || null,
                    onChange: (value) => {
                        setEventType(value || '');
                        resetPage();
                    },
                    clearable: true,
                    width: 200
                }
            ]
        }),
        h(ErrorAlert, { error }),
        events && events.length === 0 && !loading
            ? h(EmptyState, {
                  label: filterLabel(
                      hasFilters,
                      'No audit events yet.',
                      'No events match these filters.'
                  )
              })
            : events
              ? h(
                    TableShell,
                    { loading },
                    h(
                        M.Table,
                        { highlightOnHover: true, verticalSpacing: 'sm', horizontalSpacing: 'md' },
                        h(
                            M.Table.Thead,
                            null,
                            h(
                                M.Table.Tr,
                                null,
                                h(M.Table.Th, null, 'When'),
                                h(M.Table.Th, null, 'Event'),
                                h(M.Table.Th, null, 'Actor'),
                                h(M.Table.Th, null, 'Record'),
                                h(M.Table.Th, null, 'Notes')
                            )
                        ),
                        h(
                            M.Table.Tbody,
                            null,
                            events.map((event) =>
                                h(
                                    M.Table.Tr,
                                    { key: event.pk },
                                    h(M.Table.Td, null, formatDateTime(event.created)),
                                    h(M.Table.Td, null, event.event_label),
                                    h(M.Table.Td, null, event.actor || 'System'),
                                    h(
                                        M.Table.Td,
                                        null,
                                        event.loan_reference || event.request_reference || '—'
                                    ),
                                    h(M.Table.Td, null, event.notes || '—')
                                )
                            )
                        )
                    )
                )
              : h(Loading),
        total > 0
            ? h(TableFooter, {
                  total,
                  limit,
                  page,
                  onPage: setPage,
                  onLimit: (value) => {
                      setLimit(value);
                      resetPage();
                  },
                  label: 'events'
              })
            : null
    );
}

function AdminConsole({ context }) {
    const api = context.api;
    const [tab, setTab] = useState('requests');
    const [access, setAccess] = useState(null);
    const [accessError, setAccessError] = useState('');
    const [statsKey, setStatsKey] = useState(0);
    const refreshStats = () => setStatsKey((value) => value + 1);

    // The same native page serves loan staff and ordinary requesters.  Read
    // the role flags from the API so requesters only see their own tabs.
    useEffect(() => {
        let active = true;
        api.get('/plugin/loan/api/stats/')
            .then((response) => {
                if (active) setAccess(response.data || {});
            })
            .catch((err) => {
                if (active) setAccessError(errorText(err));
            });
        return () => {
            active = false;
        };
    }, [api, statsKey]);

    const isManager = Boolean(access?.is_manager);
    const canHandout = Boolean(access?.can_handout);
    const canManage = Boolean(access?.can_manage_staff);
    const requestUrl = context.context?.request_url || '/plugin/loan/request/';

    const tabs = [
        { value: 'requests', label: 'Requests' },
        { value: 'loans', label: 'Loans' }
    ];
    if (canHandout) tabs.push({ value: 'handout', label: 'Handout' });
    if (canManage) {
        tabs.push({ value: 'staff', label: 'Staff' });
        tabs.push({ value: 'setup', label: 'Setup' });
    }
    if (isManager) tabs.push({ value: 'history', label: 'History' });

    return h(
        M.Stack,
        { gap: 'md' },
        h(
            M.Group,
            { justify: 'space-between', align: 'flex-end' },
            h(
                M.Stack,
                { gap: 2 },
                h(M.Title, { order: 3 }, isManager ? 'Loan Manager' : 'My requests and loans'),
                h(
                    M.Text,
                    { size: 'sm', c: 'dimmed' },
                    isManager
                        ? 'Approve requests, hand out items and process returns.'
                        : 'Track your loan requests and borrowed items.'
                )
            ),
            h(
                M.Group,
                { gap: 'sm' },
                h(M.Badge, { variant: 'light' }, 'InvenTree'),
                h(
                    M.Anchor,
                    { href: requestUrl, target: '_blank' },
                    'Open request form'
                )
            )
        ),
        h(ErrorAlert, { error: accessError }),
        access
            ? h(
                  M.SimpleGrid,
                  { cols: { base: 2, sm: 4 }, spacing: 'sm' },
                  h(StatCard, {
                      label: 'Pending requests',
                      value: access.pending_requests,
                      color: 'yellow.7'
                  }),
                  h(StatCard, {
                      label: 'Approved',
                      value: access.approved_requests,
                      color: 'blue.6'
                  }),
                  h(StatCard, {
                      label: 'On loan',
                      value: access.active_loans,
                      color: 'green.6'
                  }),
                  h(StatCard, {
                      label: 'Overdue',
                      value: access.overdue_loans,
                      color: 'red.6'
                  })
              )
            : null,
        h(
            M.Tabs,
            { value: tab, onChange: setTab, keepMounted: false },
            h(
                M.Tabs.List,
                null,
                ...tabs.map((item) =>
                    h(M.Tabs.Tab, { value: item.value, key: item.value }, item.label)
                )
            ),
            h(
                M.Tabs.Panel,
                { value: 'requests', pt: 'md' },
                h(RequestsPanel, { context, onDataChanged: refreshStats })
            ),
            h(
                M.Tabs.Panel,
                { value: 'loans', pt: 'md' },
                h(LoansPanel, { context, onDataChanged: refreshStats })
            ),
            canHandout
                ? h(
                      M.Tabs.Panel,
                      { value: 'handout', pt: 'md' },
                      h(HandoutPanel, { context, onDataChanged: refreshStats })
                  )
                : null,
            canManage
                ? h(M.Tabs.Panel, { value: 'staff', pt: 'md' }, h(StaffPanel, { context }))
                : null,
            canManage
                ? h(M.Tabs.Panel, { value: 'setup', pt: 'md' }, h(SetupPanel, { context }))
                : null,
            isManager
                ? h(M.Tabs.Panel, { value: 'history', pt: 'md' }, h(HistoryPanel, { context }))
                : null
        )
    );
}

function withRequestFallback(context) {
    // InvenTree 1.6+ passes the full plugin context, with the server-side
    // context nested under `context.context`.  Native routes do not receive
    // server context, so provide a sensible default for the request link.
    const data = context?.context || {};
    return {
        ...context,
        context: {
            ...data,
            request_url: data.request_url || '/plugin/loan/request/'
        }
    };
}

/**
 * Entry point for the native plugin settings page.
 *
 * InvenTree renders this inside the standard plugin administration drawer.
 */
export function renderPluginSettings(context) {
    return h(AdminConsole, { context: withRequestFallback(context) });
}

/**
 * Entry point for the native InvenTree route (/plugin/loan/management).
 *
 * This is what the top-level "Loans" navigation tab opens.  It receives the
 * normal InvenTree plugin context (React Router navigation, axios client,
 * user state, theme, ...), so the page behaves like any core InvenTree page.
 */
export function renderLoanPage(context) {
    return h(AdminConsole, { context: withRequestFallback(context) });
}

/**
 * Entry point for the native request detail page
 * (/web/plugin/loan/requests/<pk>).
 */
export function renderRequestPage(context) {
    const match = window.location.pathname.match(/\/plugin\/loan\/requests\/(\d+)/);
    if (!match) {
        return h(M.Alert, { color: 'red', title: 'Request not found' }, 'The request reference in the URL is invalid.');
    }
    return h(RequestDetailPage, {
        context: withRequestFallback(context),
        requestId: Number(match[1])
    });
}

/**
 * Entry point for the spotlight (Ctrl/Cmd+K) action.
 */
export function performLoanSpotlightAction(context) {
    const url = context?.context?.url || '/plugin/loan/management';
    if (context?.navigate) {
        context.navigate(url);
    }
}

/**
 * Entry point for the dashboard card.
 */
export function renderLoanDashboardItem(context) {
    return h(LoanDashboardCard, { context });
}

function LoanDashboardCard({ context }) {
    const data = context?.context || {};
    const openDesk = () => {
        if (context?.navigate) {
            context.navigate('/plugin/loan/management');
        } else {
            window.location.href = data.management_url || '/plugin/loan/management';
        }
    };

    return h(
        M.Card,
        { withBorder: true, padding: 'md', h: '100%' },
        h(
            M.Stack,
            { gap: 'sm', h: '100%', justify: 'space-between' },
            h(
                M.Stack,
                { gap: 4 },
                h(M.Text, { fw: 700 }, 'Loans'),
                h(
                    M.Text,
                    { size: 'sm', c: 'dimmed' },
                    data.is_manager
                        ? 'Request items or open the loan management console.'
                        : 'Request an item and track your loan status.'
                )
            ),
            h(
                M.Group,
                { grow: true },
                h(
                    M.Button,
                    {
                        component: 'a',
                        href: data.request_url,
                        variant: 'light',
                        size: 'xs'
                    },
                    'Request a loan'
                ),
                data.is_manager
                    ? h(
                          M.Button,
                          { size: 'xs', onClick: openDesk },
                          'Open loan desk'
                      )
                    : null
            )
        )
    );
}

