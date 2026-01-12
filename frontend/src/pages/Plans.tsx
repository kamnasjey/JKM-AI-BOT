import { useEffect, useMemo, useState } from 'react';

import { apiFetch, apiGetJson } from '../lib/apiClient';
import { buildAuthHeaders } from '../lib/auth';

type Plan = { plan_id: string; label: string; max_pairs: number };

type MeResponse = {
  ok: boolean;
  user: { email?: string | null; is_admin?: boolean };
  plan: { plan_id: string; label: string; status: string; max_pairs: number };
};

export function PlansPage() {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [selectedPlan, setSelectedPlan] = useState<string>('pro');
  const [payerEmail, setPayerEmail] = useState<string>('');
  const [status, setStatus] = useState<string>('');
  const [error, setError] = useState<string>('');

  const headers = useMemo(() => buildAuthHeaders({ 'Content-Type': 'application/json' }), []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setError('');
      try {
        const [meRes, plansRes] = await Promise.all([
          apiGetJson<MeResponse>('/api/me', { headers }),
          apiGetJson<{ ok: boolean; plans: Plan[] }>('/api/billing/plans', { headers }),
        ]);
        if (cancelled) return;
        setMe(meRes);
        setPlans(Array.isArray(plansRes.plans) ? plansRes.plans : []);
        const email = String(meRes?.user?.email || '').trim();
        if (email) setPayerEmail(email);
      } catch (e) {
        setError(String((e as any)?.message || e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [headers]);

  const submitManualRequest = async () => {
    setStatus('');
    setError('');
    try {
      const res = await apiFetch('/api/billing/manual-request', {
        method: 'POST',
        headers,
        body: JSON.stringify({ plan_id: selectedPlan, payer_email: payerEmail }),
      });

      if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw new Error(text || `HTTP ${res.status}`);
      }

      setStatus('Request submitted. Admin will approve after verifying transfer.');
    } catch (e) {
      setError(String((e as any)?.message || e));
    }
  };

  return (
    <div className="p-4 text-white max-w-3xl">
      <h2 className="text-lg font-semibold">Plans</h2>

      {me ? (
        <div className="mt-2 text-sm text-gray-300">
          Current: <span className="font-semibold text-yellow-400">{me.plan.label}</span> (max {me.plan.max_pairs} pairs)
        </div>
      ) : null}

      {error ? (
        <div className="mt-3 p-3 rounded border border-red-800 bg-red-900/20 text-red-200 break-words">
          {error}
        </div>
      ) : null}

      <div className="mt-4 grid gap-3">
        {plans.map((p) => (
          <label
            key={p.plan_id}
            className={`p-3 rounded border cursor-pointer ${selectedPlan === p.plan_id ? 'border-yellow-500 bg-gray-800' : 'border-gray-700 bg-gray-900'}`}
          >
            <div className="flex items-center justify-between">
              <div>
                <div className="font-semibold">{p.label}</div>
                <div className="text-sm text-gray-400">Max pairs: {p.max_pairs}</div>
              </div>
              <input
                type="radio"
                name="plan"
                checked={selectedPlan === p.plan_id}
                onChange={() => setSelectedPlan(p.plan_id)}
              />
            </div>
          </label>
        ))}
      </div>

      <div className="mt-6 p-4 rounded border border-gray-700 bg-gray-900">
        <div className="font-semibold">Bank transfer (manual approval)</div>
        <div className="text-sm text-gray-300 mt-1">
          After you transfer, enter the Gmail you used for the transfer. Admin will verify and enable access.
        </div>

        <div className="mt-3">
          <label className="text-sm text-gray-300">Your Gmail (payer email)</label>
          <input
            className="mt-1 w-full p-2 bg-gray-800 rounded border border-gray-700 focus:outline-none focus:border-yellow-500"
            value={payerEmail}
            onChange={(e) => setPayerEmail(e.target.value)}
            placeholder="yourname@gmail.com"
          />
        </div>

        <button
          className="mt-3 px-4 py-2 rounded bg-yellow-500 text-black font-semibold"
          onClick={submitManualRequest}
          type="button"
          disabled={!payerEmail.trim() || selectedPlan === 'free'}
          title={selectedPlan === 'free' ? 'Free does not require approval' : ''}
        >
          Submit request
        </button>

        {status ? <div className="mt-3 text-sm text-green-300">{status}</div> : null}
      </div>
    </div>
  );
}
