import * as React from 'react';
import {
  Button, Card, CardHeader, CardFooter, Input, Dropdown, Option,
  Textarea, Field, Switch, Divider, InfoLabel, makeStyles, TabList, Tab,
  Toaster, Toast, ToastTitle, useId, useToastController
} from '@fluentui/react-components';
import { AddCircleRegular, DismissRegular } from '@fluentui/react-icons';

const useStyles = makeStyles({
  page: { maxWidth: 960, margin: '0 auto', padding: '2rem 1rem' },
  grid: { display: 'grid', gap: '1rem', gridTemplateColumns: '1fr' },
  two: { display: 'grid', gap: '1rem', gridTemplateColumns: '1fr 1fr' },
  three: { display: 'grid', gap: '1rem', gridTemplateColumns: '1fr 1fr 1fr' },
  actions: { display: 'flex', gap: '.75rem', justifyContent: 'flex-end' },
  subtle: { color: 'var(--colorNeutralForeground3)' },
});

type Shift = {
  shift_id?: string;
  dateISO: string;
  timeHHmm: string;          // accepts "17:30" or "05:30 PM"
  tz: string;
  notes?: string;
};

type Profile = {
  user_id?: string;
  name: string;
  email: string;
  phone_e164: string;
};

const timezones = ['America/New_York','America/Chicago','America/Denver','America/Los_Angeles','UTC'];

// Use Vite proxy (/api -> 7071) or set VITE_API_BASE=http://localhost:7071
const API_BASE = (import.meta as any).env?.VITE_API_BASE ?? '';

function parseTimeTo24h(value: string): { h: number; m: number } | null {
  if (!value) return null;
  const v = value.trim();

  // Case 1: 24h "HH:mm"
  const m24 = /^(\d{1,2}):(\d{2})$/.exec(v);
  if (m24) {
    const h = Number(m24[1]);
    const m = Number(m24[2]);
    if (Number.isFinite(h) && Number.isFinite(m)) return { h, m };
  }

  // Case 2: 12h "hh:mm AM/PM"
  const m12 = /^(\d{1,2}):(\d{2})\s*([AP]M)$/i.exec(v);
  if (m12) {
    let h = Number(m12[1]);
    const m = Number(m12[2]);
    const pm = m12[3].toUpperCase() === 'PM';
    if (h === 12) h = pm ? 12 : 0; else if (pm) h += 12;
    return { h, m };
  }

  return null;
}

function toLocalISO(dateISO: string, timeStr: string) {
  if (!dateISO || !timeStr) return '';
  const t = parseTimeTo24h(timeStr);
  if (!t) return ''; // guard if browser gives something unexpected
  const [Y, M, D] = dateISO.split('-').map(Number);
  const d = new Date(Y, (M - 1), D, t.h, t.m, 0, 0);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00`;
}

async function fetchJson(url: string, init?: RequestInit) {
  const res = await fetch(url, init);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    const msg = text || `${res.status} ${res.statusText}`;
    throw new Error(msg);
  }
  const ct = res.headers.get('content-type') ?? '';
  if (!ct.includes('application/json')) return {} as any;
  return res.json();
}

export default function ShiftPortal() {
  const s = useStyles();

  // Fluent v9 toaster
  const toasterId = useId('toaster');
  const { dispatchToast } = useToastController(toasterId);
  const toast = (msg: string, intent: 'success' | 'info' | 'warning' | 'error' = 'info') =>
    dispatchToast(<Toast><ToastTitle>{msg}</ToastTitle></Toast>, { intent });

  const [authed, setAuthed] = React.useState(false);
  const [profile, setProfile] = React.useState<Profile>({ name: '', email: '', phone_e164: '' });
  const [shifts, setShifts] = React.useState<Shift[]>([]);
  const [newShift, setNewShift] = React.useState<Shift>({ dateISO: '', timeHHmm: '', tz: 'America/New_York', notes: '' });
  const [ackSMS, setAckSMS] = React.useState(false);
  const [ackEmail, setAckEmail] = React.useState(true);

  // Optional identity probe for /.auth/me
  React.useEffect(() => {
    (async () => {
      try {
        const res = await fetch('/.auth/me');
        if (res.ok) {
          const data = await res.json();
          const p = data?.clientPrincipal;
          if (p) {
            setAuthed(true);
            const email = p.userDetails || '';
            setProfile(pr => ({ ...pr, name: pr.name || p.userId?.slice(0, 8) || '', email }));
          }
        }
      } catch { /* ignore */ }
    })();
  }, []);

  async function saveProfile(): Promise<string> {
    const data = await fetchJson(`${API_BASE}/api/users`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(profile),
    });
    const uid = (data as any).user_id as string;
    setProfile(p => ({ ...p, user_id: uid }));
    toast('Profile saved', 'success');
    return uid;
  }

  async function addShift() {
    try {
      // Ensure we have a user_id (create profile if needed)
      let uid = profile.user_id;
      if (!uid) uid = await saveProfile();

      // Validate date/time
      if (!newShift.dateISO || !newShift.timeHHmm) {
        toast('Pick a date and time first.', 'warning');
        return;
      }
      const shift_local_iso = toLocalISO(newShift.dateISO, newShift.timeHHmm);
      if (!shift_local_iso) {
        toast('Bad time format. Try 24-hour (e.g., 17:30) or 12-hour (e.g., 05:30 PM).', 'warning');
        return;
      }

      const payload = {
        user_id: uid,
        shift_local_iso,
        tz: newShift.tz,          // only shift timezone now
        notify_sms: ackSMS,
        notify_email: ackEmail,
        notes: newShift.notes,
      };

      const data = await fetchJson(`${API_BASE}/api/shifts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      toast('Shift scheduled', 'success');
      setShifts(prev => [
        {
          shift_id: (data as any).shift_id,
          dateISO: newShift.dateISO,
          timeHHmm: newShift.timeHHmm,
          tz: newShift.tz,
          notes: newShift.notes,
        },
        ...prev,
      ]);
      setNewShift({ dateISO: '', timeHHmm: '', tz: newShift.tz, notes: '' });
    } catch (err: any) {
      console.error(err);
      toast(`Could not schedule shift: ${err.message ?? err}`, 'error');
    }
  }

  async function loadMyShifts() {
    if (!profile.user_id) return;
    try {
      const data = await fetchJson(`${API_BASE}/api/shifts?user_id=${encodeURIComponent(profile.user_id)}`);
      const items = (data as any).items ?? [];
      setShifts(
        items.map((it: any) => ({
          shift_id: it.shift_id,
          dateISO: it.shift_start_local.split('T')[0],
          timeHHmm: it.shift_start_local.split('T')[1].slice(0, 5),
          tz: it.tz,
          notes: it.notes || '',
        })),
      );
    } catch (err: any) {
      toast(`Could not load shifts: ${err.message ?? err}`, 'error');
    }
  }

  React.useEffect(() => { loadMyShifts(); }, [profile.user_id]);

  return (
    <div className={s.page}>
      <Toaster toasterId={toasterId} position="top-end" />
      <Card>
        <CardHeader
          header={<h2>Patient Shift Portal</h2>}
          description={<span className={s.subtle}>Book your shift and we’ll remind you the day before and two hours before.</span>}
        />
        <Divider />
        <div className={s.grid}>
          <TabList defaultSelectedValue="book">
            <Tab value="book">Book Shift</Tab>
            <Tab value="history">My Shifts</Tab>
          </TabList>

          {/* Your Info (no personal timezone) */}
          <section className={s.grid}>
            <h3>Your Info</h3>
            <div className={s.two}>
              <Field label="Full name" validationState={profile.name ? 'none' : 'warning'}>
                <Input value={profile.name} onChange={(_, v) => setProfile(p => ({ ...p, name: v.value }))} disabled={authed} />
              </Field>
              <Field
                label={<InfoLabel info="Used for confirmations and reminders.">Email</InfoLabel>}
                validationState={/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(profile.email) ? 'none' : 'warning'}
              >
                <Input type="email" value={profile.email} onChange={(_, v) => setProfile(p => ({ ...p, email: v.value }))} disabled={authed} />
              </Field>
            </div>
            <div className={s.two}>
              <Field
                label={<InfoLabel info="Use E.164 format, e.g., +15551234567">Mobile phone</InfoLabel>}
                validationState={/^\+\d{8,15}$/.test(profile.phone_e164) ? 'none' : 'warning'}
              >
                <Input value={profile.phone_e164} onChange={(_, v) => setProfile(p => ({ ...p, phone_e164: v.value }))} />
              </Field>
              {/* filler to keep grid balanced */}
              <div />
            </div>
          </section>

          <Divider />

          {/* Book a shift (has only shift timezone) */}
          <section className={s.grid}>
            <h3>Book a shift</h3>
            <div className={s.three}>
              <Field label="Date" validationState={newShift.dateISO ? 'none' : 'warning'}>
                <Input type="date" value={newShift.dateISO} onChange={(_, v) => setNewShift(s => ({ ...s, dateISO: v.value }))} />
              </Field>
              <Field label="Start time" validationState={newShift.timeHHmm ? 'none' : 'warning'}>
                <Input type="time" value={newShift.timeHHmm} onChange={(_, v) => setNewShift(s => ({ ...s, timeHHmm: v.value }))} />
              </Field>
              <Field label="Shift time zone">
                <Dropdown selectedOptions={[newShift.tz]} onOptionSelect={(_, d) => setNewShift(s => ({ ...s, tz: String(d.optionValue) }))}>
                  {timezones.map(tz => (
                    <Option key={tz} value={tz}>{tz}</Option>
                  ))}
                </Dropdown>
              </Field>
            </div>

            <Field label={<InfoLabel info="Optional details clinicians should know.">Notes</InfoLabel>}>
              <Textarea resize="vertical" value={newShift.notes} onChange={(_, v) => setNewShift(s => ({ ...s, notes: v.value }))} />
            </Field>

            <div className={s.two}>
              <Field label="SMS reminder"><Switch checked={ackSMS} onChange={(_, d) => setAckSMS(!!d.checked)} /></Field>
              <Field label="Email reminder"><Switch checked={ackEmail} onChange={(_, d) => setAckEmail(!!d.checked)} /></Field>
            </div>

            <div className={s.actions}>
              <Button appearance="secondary" icon={<DismissRegular />}
                onClick={() => setNewShift({ dateISO: '', timeHHmm: '', tz: newShift.tz, notes: '' })}>
                Clear
              </Button>
              <Button appearance="primary" icon={<AddCircleRegular />} onClick={addShift}>
                Schedule shift
              </Button>
            </div>
          </section>

          <Divider />

          <section className={s.grid}>
            <h3>My shifts</h3>
            {shifts.length === 0 && <p className={s.subtle}>No shifts yet. Schedule one above.</p>}
            <div className={s.grid}>
              {shifts.map(sh => (
                <Card key={sh.shift_id} style={{ borderRadius: '16px' }}>
                  <CardHeader
                    header={<strong>{sh.dateISO} at {sh.timeHHmm} ({sh.tz})</strong>}
                    description={sh.notes || '—'}
                  />
                  <CardFooter>
                    <div className={s.actions}>
                      <Button size="small" appearance="secondary">Reschedule</Button>
                      <Button size="small" appearance="secondary">Cancel</Button>
                    </div>
                  </CardFooter>
                </Card>
              ))}
            </div>
          </section>
        </div>
      </Card>
    </div>
  );
}
