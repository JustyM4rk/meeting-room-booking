import { useEffect, useRef, useState } from 'react';
import axios from 'axios';

interface Proposal {
  room_id: string;
  room_name: string;
  start_time: string;
  end_time: string;
  title: string;
  participants_count: number;
  services: string;
  comment: string;
  requires_approval: boolean;
}

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  proposal?: Proposal;
  proposalState?: 'open' | 'confirmed' | 'dismissed';
}

const MAX_HISTORY = 10;

const formatTime = (value: string) =>
  new Date(value).toLocaleString('uk-UA', { dateStyle: 'medium', timeStyle: 'short' });

const errorText = (e: unknown, fallback: string) => {
  if (axios.isAxiosError(e)) {
    const detail = e.response?.data?.detail;
    if (typeof detail === 'string') return detail;
  }
  return fallback;
};

export default function ChatAssistant() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading, open]);

  const send = async () => {
    const text = input.trim();
    if (!text || loading) return;

    const next: ChatMessage[] = [...messages, { role: 'user', content: text }];
    setMessages(next);
    setInput('');
    setLoading(true);

    try {
      // Only plain text goes back to the server; proposals are never sent as instructions
      const history = next.slice(-MAX_HISTORY).map(m => ({ role: m.role, content: m.content }));
      const res = await axios.post('/assistant/chat', { messages: history });
      const proposal: Proposal | undefined = res.data.proposal ?? undefined;
      setMessages([
        ...next,
        {
          role: 'assistant',
          content: res.data.reply,
          proposal,
          proposalState: proposal ? 'open' : undefined,
        },
      ]);
    } catch (e) {
      setMessages([
        ...next,
        { role: 'assistant', content: `⚠️ ${errorText(e, 'Не вдалося отримати відповідь асистента.')}` },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const setProposalState = (index: number, state: ChatMessage['proposalState']) =>
    setMessages(prev => prev.map((m, i) => (i === index ? { ...m, proposalState: state } : m)));

  const confirm = async (index: number, proposal: Proposal) => {
    const userStr = localStorage.getItem('user');
    if (!userStr) return;
    const user = JSON.parse(userStr);

    try {
      // The normal booking endpoint: it applies the same rules and permissions as the booking form
      const res = await axios.post('/bookings/', {
        room_id: proposal.room_id,
        user_id: user.user_id,
        start_time: proposal.start_time,
        end_time: proposal.end_time,
        title: proposal.title,
        participants_count: proposal.participants_count,
        services: proposal.services,
        comment: proposal.comment,
      });
      setProposalState(index, 'confirmed');
      const text =
        res.data.status === 'pending'
          ? '⏳ Заявку прийнято. Бронювання довше 3 годин, воно чекає підтвердження адміністратора.'
          : `✅ Готово! Кімнату ${proposal.room_name} заброньовано. Оновіть сторінку, щоб побачити зміни.`;
      setMessages(prev => [...prev, { role: 'assistant', content: text }]);
    } catch (e) {
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: `⚠️ ${errorText(e, 'Не вдалося створити бронювання.')}` },
      ]);
    }
  };

  return (
    <>
      {open && (
        <div className="fixed bottom-24 right-6 z-50 flex h-[32rem] w-96 max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-2xl">
          <div className="flex items-center justify-between bg-blue-600 px-4 py-3 text-white">
            <span className="font-bold">🤖 AI-асистент</span>
            <button onClick={() => setOpen(false)} className="text-xl leading-none hover:opacity-80" aria-label="Закрити">
              ×
            </button>
          </div>

          <div className="flex-1 space-y-3 overflow-y-auto bg-gray-50 p-3 text-sm">
            <div className="max-w-[85%] rounded-xl bg-white px-3 py-2 text-gray-700 shadow-sm">
              Привіт! Я допоможу знайти кімнату і підготувати бронювання. Наприклад: «Потрібна кімната на 6 осіб
              завтра о 15:00».
            </div>

            {messages.map((m, i) => (
              <div key={i} className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
                <div
                  className={`max-w-[85%] whitespace-pre-wrap rounded-xl px-3 py-2 shadow-sm ${
                    m.role === 'user' ? 'bg-blue-600 text-white' : 'bg-white text-gray-700'
                  }`}
                >
                  {m.content}

                  {m.proposal && m.proposalState === 'open' && (
                    <div className="mt-2 space-y-1 rounded-lg border border-blue-200 bg-blue-50 p-2 text-xs text-gray-700">
                      <div className="font-bold">{m.proposal.title}</div>
                      <div>🏢 {m.proposal.room_name}</div>
                      <div>
                        🕒 {formatTime(m.proposal.start_time)} – {formatTime(m.proposal.end_time)}
                      </div>
                      <div>👥 {m.proposal.participants_count}</div>
                      {m.proposal.services && <div>🔧 {m.proposal.services}</div>}
                      {m.proposal.requires_approval && (
                        <div className="text-amber-600">Потрібне підтвердження адміністратора (понад 3 год)</div>
                      )}
                      <div className="flex gap-2 pt-1">
                        <button
                          onClick={() => confirm(i, m.proposal!)}
                          className="rounded bg-green-600 px-3 py-1 font-bold text-white hover:bg-green-700"
                        >
                          Підтвердити
                        </button>
                        <button
                          onClick={() => setProposalState(i, 'dismissed')}
                          className="rounded border border-gray-300 px-3 py-1 text-gray-600 hover:bg-gray-100"
                        >
                          Скасувати
                        </button>
                      </div>
                    </div>
                  )}
                  {m.proposal && m.proposalState === 'confirmed' && (
                    <div className="mt-2 text-xs text-green-600">✔ Підтверджено</div>
                  )}
                  {m.proposal && m.proposalState === 'dismissed' && (
                    <div className="mt-2 text-xs text-gray-400">Скасовано</div>
                  )}
                </div>
              </div>
            ))}

            {loading && <div className="text-xs text-gray-400">Асистент друкує…</div>}
            <div ref={bottomRef} />
          </div>

          <div className="flex gap-2 border-t border-gray-200 bg-white p-3">
            <input
              value={input}
              maxLength={500}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && send()}
              placeholder="Напишіть повідомлення…"
              className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />
            <button
              onClick={send}
              disabled={loading || !input.trim()}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-bold text-white hover:bg-blue-700 disabled:opacity-50"
            >
              ➤
            </button>
          </div>
        </div>
      )}

      <button
        onClick={() => setOpen(o => !o)}
        className="fixed bottom-6 right-6 z-50 flex h-14 w-14 items-center justify-center rounded-full bg-blue-600 text-2xl text-white shadow-lg transition hover:bg-blue-700"
        aria-label="AI-асистент"
      >
        {open ? '×' : '💬'}
      </button>
    </>
  );
}
