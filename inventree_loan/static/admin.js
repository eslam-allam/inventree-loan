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
const { useCallback, useEffect, useMemo, useState } = React;

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

function useRequestList(api, reloadKey) {
    const [data, setData] = useState(null);
    const [error, setError] = useState('');
    useEffect(() => {
        let active = true;
        setError('');
        api.get('/plugin/loan/api/requests/')
            .then((response) => {
                if (active) setData(response.data?.results || []);
            })
            .catch((err) => {
                if (active) setError(errorText(err));
            });
        return () => {
            active = false;
        };
    }, [api, reloadKey]);
    return { data, error, loading: data === null && !error };
}

function RequestsPanel({ context }) {
    const api = context.api;
    const [reloadKey, setReloadKey] = useState(0);
    const { data: requests, error, loading } = useRequestList(api, reloadKey);
    const [action, setAction] = useState(null);
    const [notes, setNotes] = useState('');
    const [saving, setSaving] = useState(false);
    const [actionError, setActionError] = useState('');

    const submitAction = useCallback(() => {
        if (!action) return;
        setSaving(true);
        setActionError('');
        api.post(`/plugin/loan/api/requests/${action.id}/${action.type}/`, { notes })
            .then(() => {
                setAction(null);
                setNotes('');
                setReloadKey((value) => value + 1);
            })
            .catch((err) => setActionError(errorText(err)))
            .finally(() => setSaving(false));
    }, [action, api, notes]);

    if (loading) return h(Loading);
    if (error) return h(ErrorAlert, { error });

    return h(
        M.Stack,
        { gap: 'md' },
        h(
            M.Group,
            { justify: 'space-between' },
            h(M.Title, { order: 4 }, 'Requests'),
            h(M.Anchor, { href: context.context?.request_url, target: '_blank' }, 'Open request form')
        ),
        requests.length === 0
            ? h(EmptyState, { label: 'No loan requests yet.' })
            : h(
                  M.Paper,
                  { withBorder: true },
                  h(
                      'div',
                      { style: { overflowX: 'auto' } },
                      h(
                          M.Table,
                          { highlightOnHover: true, verticalSpacing: 'sm' },
                          h(
                              M.Table.Thead,
                              null,
                              h(
                                  M.Table.Tr,
                                  null,
                                  h(M.Table.Th, null, 'Reference'),
                                  h(M.Table.Th, null, 'Requester'),
                                  h(M.Table.Th, null, 'Items'),
                                  h(M.Table.Th, null, 'Status'),
                                  h(M.Table.Th, null, 'Created'),
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
                                      h(M.Table.Td, null, h(M.Text, { fw: 600 }, request.reference)),
                                      h(M.Table.Td, null, request.requester),
                                      h(M.Table.Td, null, request.item_count),
                                      h(
                                          M.Table.Td,
                                          null,
                                          h(StatusBadge, {
                                              status: request.status,
                                              label: request.status_display
                                          })
                                      ),
                                      h(M.Table.Td, null, formatDate(request.created)),
                                      h(
                                          M.Table.Td,
                                          null,
                                          request.can_approve
                                              ? h(
                                                    M.Group,
                                                    { gap: 'xs', wrap: 'nowrap' },
                                                    h(
                                                        M.Button,
                                                        {
                                                            size: 'xs',
                                                            color: 'green',
                                                            onClick: () => {
                                                                setAction({
                                                                    id: request.pk,
                                                                    type: 'approve'
                                                                });
                                                                setNotes('');
                                                                setActionError('');
                                                            }
                                                        },
                                                        'Approve'
                                                    ),
                                                    h(
                                                        M.Button,
                                                        {
                                                            size: 'xs',
                                                            color: 'red',
                                                            variant: 'light',
                                                            onClick: () => {
                                                                setAction({
                                                                    id: request.pk,
                                                                    type: 'reject'
                                                                });
                                                                setNotes('');
                                                                setActionError('');
                                                            }
                                                        },
                                                        'Reject'
                                                    )
                                                )
                                              : request.status === 'approved' && request.can_checkout
                                                ? h(
                                                      M.Button,
                                                      {
                                                          size: 'xs',
                                                          onClick: () => {
                                                              setAction({
                                                                  id: request.pk,
                                                                  type: 'checkout'
                                                              });
                                                              setNotes('');
                                                              setActionError('');
                                                          }
                                                      },
                                                      'Hand out'
                                                  )
                                                : h(M.Text, { size: 'sm', c: 'dimmed' }, '—')
                                      )
                                  )
                              )
                          )
                      )
                  )
              ),
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
                                    setSaving(true);
                                    setActionError('');
                                    api.post('/plugin/loan/api/checkout/', {
                                        request_id: action.id,
                                        notes
                                    })
                                        .then(() => {
                                            setAction(null);
                                            setNotes('');
                                            setReloadKey((value) => value + 1);
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

function LoansPanel({ context }) {
    const api = context.api;
    const [reloadKey, setReloadKey] = useState(0);
    const [loans, setLoans] = useState(null);
    const [error, setError] = useState('');
    const [returnLoan, setReturnLoan] = useState(null);

    useEffect(() => {
        let active = true;
        setError('');
        api.get('/plugin/loan/api/loans/')
            .then((response) => {
                if (active) setLoans(response.data?.results || []);
            })
            .catch((err) => {
                if (active) setError(errorText(err));
            });
        return () => {
            active = false;
        };
    }, [api, reloadKey]);

    if (loans === null && !error) return h(Loading);
    if (error) return h(ErrorAlert, { error });

    return h(
        M.Stack,
        { gap: 'md' },
        h(M.Title, { order: 4 }, 'Loans'),
        loans.length === 0
            ? h(EmptyState, { label: 'No loans have been issued yet.' })
            : h(
                  M.Paper,
                  { withBorder: true },
                  h(
                      'div',
                      { style: { overflowX: 'auto' } },
                      h(
                          M.Table,
                          { highlightOnHover: true, verticalSpacing: 'sm' },
                          h(
                              M.Table.Thead,
                              null,
                              h(
                                  M.Table.Tr,
                                  null,
                                  h(M.Table.Th, null, 'Reference'),
                                  h(M.Table.Th, null, 'Borrower'),
                                  h(M.Table.Th, null, 'Items'),
                                  h(M.Table.Th, null, 'Due'),
                                  h(M.Table.Th, null, 'Status'),
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
                                      h(M.Table.Td, null, h(M.Text, { fw: 600 }, loan.reference)),
                                      h(M.Table.Td, null, loan.borrower),
                                      h(M.Table.Td, null, loan.item_count),
                                      h(
                                          M.Table.Td,
                                          { style: loan.is_overdue ? { color: 'var(--mantine-color-red-6)' } : null },
                                          formatDate(loan.due_at)
                                      ),
                                      h(
                                          M.Table.Td,
                                          null,
                                          h(StatusBadge, {
                                              status: loan.status,
                                              label: loan.status_display
                                          })
                                      ),
                                      h(
                                          M.Table.Td,
                                          null,
                                          loan.can_return
                                              ? h(
                                                    M.Button,
                                                    {
                                                        size: 'xs',
                                                        onClick: () => setReturnLoan(loan)
                                                    },
                                                    'Return'
                                                )
                                              : h(M.Text, { size: 'sm', c: 'dimmed' }, '—')
                                      )
                                  )
                              )
                          )
                      )
                  )
              ),
        h(ReturnModal, {
            context,
            loan: returnLoan,
            onClose: () => setReturnLoan(null),
            onSaved: () => {
                setReturnLoan(null);
                setReloadKey((value) => value + 1);
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

    useEffect(() => {
        if (!loan) {
            setDetail(null);
            setQuantities({});
            setConditions({});
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
                    qty[item.pk] = Number(item.remaining_quantity);
                    cond[item.pk] = 'good';
                });
                setQuantities(qty);
                setConditions(cond);
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
        setSaving(true);
        setError('');
        api.post(`/plugin/loan/api/loans/${detail.pk}/return/`, { lines, notes })
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
                                      h(M.Table.Td, null, item.part_name),
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

function HandoutPanel({ context }) {
    const api = context.api;
    const [requests, setRequests] = useState(null);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(null);
    const [result, setResult] = useState(null);
    const [reloadKey, setReloadKey] = useState(0);

    useEffect(() => {
        let active = true;
        setError('');
        api.get('/plugin/loan/api/requests/?status=approved')
            .then((response) => {
                if (active) setRequests(response.data?.results || []);
            })
            .catch((err) => {
                if (active) setError(errorText(err));
            });
        return () => {
            active = false;
        };
    }, [api, reloadKey]);

    const handout = (request) => {
        setBusy(request.pk);
        setError('');
        setResult(null);
        api.post('/plugin/loan/api/checkout/', { request_id: request.pk })
            .then((response) => {
                setResult(response.data);
                setReloadKey((value) => value + 1);
            })
            .catch((err) => setError(errorText(err)))
            .finally(() => setBusy(null));
    };

    if (requests === null && !error) return h(Loading);

    return h(
        M.Stack,
        { gap: 'md' },
        h(
            M.Group,
            { justify: 'space-between' },
            h(M.Title, { order: 4 }, 'Hand out'),
            h(M.Anchor, { href: context.context?.request_url, target: '_blank' }, 'Create a request')
        ),
        h(ErrorAlert, { error }),
        result
            ? h(
                  M.Alert,
                  { color: 'green', title: `Loan ${result.reference} issued` },
                  h(
                      M.Group,
                      { gap: 'sm' },
                      h(M.Anchor, { href: `/plugin/loan/loans/${result.pk}/receipt/`, target: '_blank' }, 'Print receipt'),
                      h(M.Anchor, { href: result.qr_url, target: '_blank' }, 'Open QR')
                  )
              )
            : null,
        requests && requests.length === 0
            ? h(EmptyState, { label: 'No approved requests are waiting for handout.' })
            : requests
              ? h(
                    M.Paper,
                    { withBorder: true },
                    h(
                        'div',
                        { style: { overflowX: 'auto' } },
                        h(
                            M.Table,
                            { highlightOnHover: true, verticalSpacing: 'sm' },
                            h(
                                M.Table.Thead,
                                null,
                                h(
                                    M.Table.Tr,
                                    null,
                                    h(M.Table.Th, null, 'Reference'),
                                    h(M.Table.Th, null, 'Requester'),
                                    h(M.Table.Th, null, 'Items'),
                                    h(M.Table.Th, null, 'Requested return'),
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
                                        h(M.Table.Td, null, h(M.Text, { fw: 600 }, request.reference)),
                                        h(M.Table.Td, null, request.requester),
                                        h(M.Table.Td, null, request.item_count),
                                        h(M.Table.Td, null, formatDate(request.return_by)),
                                        h(
                                            M.Table.Td,
                                            null,
                                            h(
                                                M.Button,
                                                {
                                                    size: 'xs',
                                                    loading: busy === request.pk,
                                                    onClick: () => handout(request)
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
              : null
    );
}

function StaffPanel({ context }) {
    const api = context.api;
    const [staff, setStaff] = useState(null);
    const [error, setError] = useState('');
    const [username, setUsername] = useState('');
    const [role, setRole] = useState('approver');
    const [busy, setBusy] = useState(false);
    const [reloadKey, setReloadKey] = useState(0);

    useEffect(() => {
        let active = true;
        setError('');
        api.get('/plugin/loan/api/staff/')
            .then((response) => {
                if (active) setStaff(response.data?.results || []);
            })
            .catch((err) => {
                if (active) setError(errorText(err));
            });
        return () => {
            active = false;
        };
    }, [api, reloadKey]);

    const add = () => {
        if (!username.trim()) {
            setError('Enter a username.');
            return;
        }
        setBusy(true);
        setError('');
        api.post('/plugin/loan/api/staff/', { username: username.trim(), role, active: true })
            .then(() => {
                setUsername('');
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

    if (staff === null && !error) return h(Loading);

    return h(
        M.Stack,
        { gap: 'md' },
        h(M.Title, { order: 4 }, 'Loan staff'),
        h(ErrorAlert, { error }),
        h(
            M.Paper,
            { withBorder: true, p: 'md' },
            h(
                M.Group,
                { align: 'flex-end' },
                h(M.TextInput, {
                    label: 'Username',
                    value: username,
                    onChange: (event) => setUsername(event.currentTarget.value),
                    style: { flex: 1 }
                }),
                h(M.Select, {
                    label: 'Role',
                    value: role,
                    onChange: setRole,
                    data: [
                        { value: 'approver', label: 'Approver' },
                        { value: 'desk', label: 'Loan desk' },
                        { value: 'admin', label: 'Loan administrator' }
                    ],
                    style: { width: 200 }
                }),
                h(M.Button, { loading: busy, onClick: add }, 'Add role')
            )
        ),
        staff && staff.length === 0
            ? h(EmptyState, { label: 'No loan staff roles yet. Superusers always have access.' })
            : staff
              ? h(
                    M.Paper,
                    { withBorder: true },
                    h(
                        'div',
                        { style: { overflowX: 'auto' } },
                        h(
                            M.Table,
                            { highlightOnHover: true, verticalSpacing: 'sm' },
                            h(
                                M.Table.Thead,
                                null,
                                h(
                                    M.Table.Tr,
                                    null,
                                    h(M.Table.Th, null, 'User'),
                                    h(M.Table.Th, null, 'Role'),
                                    h(M.Table.Th, null, 'Active'),
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
                                            h(M.Text, { fw: 600 }, item.username),
                                            h(M.Text, { size: 'sm', c: 'dimmed' }, item.name)
                                        ),
                                        h(M.Table.Td, null, item.role_display),
                                        h(
                                            M.Table.Td,
                                            null,
                                            h(
                                                M.Badge,
                                                { color: item.active ? 'green' : 'gray', variant: 'light' },
                                                item.active ? 'Active' : 'Inactive'
                                            )
                                        ),
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
                )
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
    const [events, setEvents] = useState(null);
    const [error, setError] = useState('');

    useEffect(() => {
        let active = true;
        setError('');
        api.get('/plugin/loan/api/events/')
            .then((response) => {
                if (active) setEvents(response.data?.results || []);
            })
            .catch((err) => {
                if (active) setError(errorText(err));
            });
        return () => {
            active = false;
        };
    }, [api]);

    if (events === null && !error) return h(Loading);

    return h(
        M.Stack,
        { gap: 'md' },
        h(M.Title, { order: 4 }, 'History'),
        h(ErrorAlert, { error }),
        events && events.length === 0
            ? h(EmptyState, { label: 'No audit events yet.' })
            : events
              ? h(
                    M.Paper,
                    { withBorder: true },
                    h(
                        'div',
                        { style: { overflowX: 'auto' } },
                        h(
                            M.Table,
                            { highlightOnHover: true, verticalSpacing: 'sm' },
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
                                        h(M.Table.Td, null, formatDate(event.created)),
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
                )
              : null
    );
}

function AdminConsole({ context }) {
    const [tab, setTab] = useState('requests');
    return h(
        M.Stack,
        { gap: 'md' },
        h(
            M.Group,
            { justify: 'space-between', align: 'flex-end' },
            h(
                M.Stack,
                { gap: 2 },
                h(M.Title, { order: 3 }, 'Loan Manager'),
                h(
                    M.Text,
                    { size: 'sm', c: 'dimmed' },
                    'Approve requests, hand out items and process returns.'
                )
            ),
            h(
                M.Group,
                { gap: 'sm' },
                h(M.Badge, { variant: 'light' }, 'InvenTree'),
                h(
                    M.Anchor,
                    { href: context.context?.request_url, target: '_blank' },
                    'Open request form'
                )
            )
        ),
        h(
            M.Tabs,
            { value: tab, onChange: setTab, keepMounted: false },
            h(
                M.Tabs.List,
                null,
                h(M.Tabs.Tab, { value: 'requests' }, 'Requests'),
                h(M.Tabs.Tab, { value: 'loans' }, 'Loans'),
                h(M.Tabs.Tab, { value: 'handout' }, 'Handout'),
                h(M.Tabs.Tab, { value: 'staff' }, 'Staff'),
                h(M.Tabs.Tab, { value: 'setup' }, 'Setup'),
                h(M.Tabs.Tab, { value: 'history' }, 'History')
            ),
            h(M.Tabs.Panel, { value: 'requests', pt: 'md' }, h(RequestsPanel, { context })),
            h(M.Tabs.Panel, { value: 'loans', pt: 'md' }, h(LoansPanel, { context })),
            h(M.Tabs.Panel, { value: 'handout', pt: 'md' }, h(HandoutPanel, { context })),
            h(M.Tabs.Panel, { value: 'staff', pt: 'md' }, h(StaffPanel, { context })),
            h(M.Tabs.Panel, { value: 'setup', pt: 'md' }, h(SetupPanel, { context })),
            h(M.Tabs.Panel, { value: 'history', pt: 'md' }, h(HistoryPanel, { context }))
        )
    );
}

export function renderPluginSettings(context) {
    return h(AdminConsole, { context });
}

export function renderLoanDashboardItem(context) {
    return h(LoanDashboardCard, { context });
}

function LoanDashboardCard({ context }) {
    const data = context?.context || {};
    const [opened, setOpened] = useState(false);

    return h(
        React.Fragment,
        null,
        h(
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
                              { size: 'xs', onClick: () => setOpened(true) },
                              'Open loan desk'
                          )
                        : null
                )
            )
        ),
        h(
            M.Modal,
            {
                opened,
                onClose: () => setOpened(false),
                fullScreen: true,
                title: 'Loan Manager',
                padding: 'md'
            },
            h(M.Container, { size: 'xl', py: 'md' }, opened ? h(AdminConsole, { context }) : null)
        )
    );
}

