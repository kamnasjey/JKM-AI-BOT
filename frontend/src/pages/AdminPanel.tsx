import { useMemo, useState } from 'react';

import { apiFetch } from '../lib/apiClient';
import { buildAuthHeaders } from '../lib/auth';

export function AdminPanel(props: { onBack: () => void }) {
  const [userEmail, setUserEmail] = useState<string>('');
  const [planId, setPlanId] = useState<string>('pro');
  const [note, setNote] = useState<string>('');
  const [status, setStatus] = useState<string>('');
  const [error, setError] = useState<string>('');

  const headers = useMemo(() => buildAuthHeaders({ 'Content-Type': 'application/json' }), []);

  const grant = async () => {
    setStatus('');
    setError('');
    try {
      const res = await apiFetch('/api/admin/grant-access', {
        method: 'POST',
        headers,
        body: JSON.stringify({ user_email: userEmail, plan_id: planId, note: note || null }),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw new Error(text || `HTTP ${res.status}`);
      }
      setStatus('Access granted.');
    } catch (e) {
      setError(String((e as any)?.message || e));
    }
  };

  return (
    <div className="p-4 text-white max-w-2xl">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Admin</h2>
        <button className="px-3 py-1 bg-gray-800 rounded border border-gray-700" onClick={props.onBack} type="button">
          Back
        </button>
      </div>

      {error ? (
        <div className="mt-3 p-3 rounded border border-red-800 bg-red-900/20 text-red-200 break-words">
          {error}
        </div>
      ) : null}

      <div className="mt-4 p-4 rounded border border-gray-700 bg-gray-900">
        <div className="font-semibold">Grant access by email</div>

        <label className="block mt-3 text-sm text-gray-300">User email</label>
        <input
          className="mt-1 w-full p-2 bg-gray-800 rounded border border-gray-700 focus:outline-none focus:border-yellow-500"
          value={userEmail}
          onChange={(e) => setUserEmail(e.target.value)}
          placeholder="user@gmail.com"
        />

        <label className="block mt-3 text-sm text-gray-300">Plan</label>
        <select
          className="mt-1 w-full p-2 bg-gray-800 rounded border border-gray-700 focus:outline-none focus:border-yellow-500"
          value={planId}
          onChange={(e) => setPlanId(e.target.value)}
        >
          <option value="free">Free</option>
          <option value="pro">Pro</option>
          <option value="pro_plus">Pro+</option>
        </select>

        <label className="block mt-3 text-sm text-gray-300">Note (optional)</label>
        <input
          className="mt-1 w-full p-2 bg-gray-800 rounded border border-gray-700 focus:outline-none focus:border-yellow-500"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Paid via bank transfer, ref ..."
        />

        <button
          className="mt-4 px-4 py-2 rounded bg-yellow-500 text-black font-semibold"
          onClick={grant}
          type="button"
          disabled={!userEmail.trim()}
        >
          Grant
        </button>

        {status ? <div className="mt-3 text-sm text-green-300">{status}</div> : null}
      </div>
    </div>
  );
}
