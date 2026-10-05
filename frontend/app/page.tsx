'use client';
import { useCallback, useEffect, useState } from 'react';
import { BrokerPanel, MarketPanel, brokerLabels, type BrokerStatus, type MarketData } from './broker-panels';

type Event = { id: string; at: string; event: string; details: Record<string, string> };
type Decision = { id: string; at: string; action: string; reason: string };
type Dashboard = {
  user: { email: string; role: string }; mode: string;
  portfolio: { equity: string; cash: string; invested: string; initial_capital: string; positions: unknown[] };
  worker_healthy: boolean; blockers: string[]; events: Event[]; decisions: Decision[];
  broker_connection: BrokerStatus;
  risk: { trade: string; position: string; exposure: string; daily_loss: string; drawdown: string };
};
const money = (value: string) => Number(value).toLocaleString('ru-RU', { style: 'currency', currency: 'RUB', maximumFractionDigits: 2 });
const pct = (value: string) => `${Number(value) * 100}%`;
const labels: Record<string, string> = { REGISTER: 'Аккаунт создан', LOGIN: 'Вход в систему', LOGOUT: 'Выход из системы', SANDBOX_BALANCE_CHANGED: 'Виртуальный капитал изменён', AUTOPILOT_START_REJECTED: 'Запуск Autopilot отклонён', AUTOPILOT_STOP: 'Autopilot остановлен', BROKER_CONNECTED:'Sandbox-токен проверен', BROKER_TOKEN_REPLACED:'Sandbox-токен заменён', BROKER_ACCOUNT_SELECTED:'Sandbox-счёт выбран', BROKER_DISCONNECTED:'Брокер отключён', BROKER_VALIDATED:'Подключение проверено', BROKER_VALIDATION_FAILED:'Проверка подключения не прошла', WATCHLIST_CHANGED:'Список наблюдения изменён', MARKET_DATA_SYNCED:'Рыночный снимок сохранён', BROKER_SYNC_FAILED:'Ошибка загрузки данных', BROKER_ENCRYPTION_KEY_ROTATED:'Ключ шифрования обновлён', SECRET_DELETE_FAILED:'Серверная копия токена требует удаления' };
const navigation = ['Обзор', 'Рынок', 'Портфель', 'Журнал решений', 'Live Brain', 'Управление риском', 'Настройки'];

async function api(path: string, body?: unknown) {
  const response = await fetch(`/api/${path}`, { method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', headers: body === undefined ? {} : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  let result;
  try { result = await response.json(); } catch { throw new Error('Сервер временно недоступен. Повторите запрос позже.'); }
  if (!response.ok) {
    const error = new Error(typeof result.detail === 'string' ? result.detail : 'Проверьте введённые данные');
    Object.assign(error, { status: response.status });
    throw error;
  }
  return result;
}

export default function Home() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [market, setMarket] = useState<MarketData | null>(null);
  const [tab, setTab] = useState('Обзор');
  const [register, setRegister] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [balance, setBalance] = useState('1000');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [connected, setConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const load = useCallback(async () => {
    try {
      const [result, prices] = await Promise.all([api('dashboard'),api('market')]);
      setData(result); setMarket(prices); setConnected(true); setLastUpdate(new Date());
    } catch (e) {
      setConnected(false);
      if ((e as Error & { status?: number }).status === 401) { setData(null); setMarket(null); setConnected(true); }
      else setError(e instanceof Error ? e.message : 'Нет связи с сервером');
    } finally { setLoaded(true); }
  }, []);
  useEffect(() => { void load(); const timer = setInterval(load, 30000); return () => clearInterval(timer); }, [load]);
  async function action(path: string, body: unknown) {
    setBusy(true); setError(''); setNotice('');
    try { const result = await api(path, body); if (result.secret_removed === false) setError(result.message); else if (result.message) setNotice(result.message); await load(); } catch (e) { setError(e instanceof Error ? e.message : 'Ошибка соединения'); await load(); }
    finally { setBusy(false); }
  }
  const activity = <div className="activity">{data?.events.length ? data.events.map(e => <article key={e.id}><span className="event-dot"/><div><strong>{labels[e.event] || e.event}</strong><small>{Object.entries(e.details).map(([key, value]) => `${key}: ${value}`).join(' · ') || 'Событие записано в журнал аудита'}</small></div><time>{new Date(e.at).toLocaleString('ru-RU')}</time></article>) : <Empty title="Событий пока нет" text="Здесь появятся подтверждённые действия системы."/>}</div>;
  const decisions = <div>{data?.decisions.length ? data.decisions.map(d => <article className="decision" key={d.id}><span className="tag">{d.action}</span><div><strong>{d.reason === 'DATA_PIPELINE_NOT_READY' ? 'Нет подтверждённых рыночных данных' : d.reason === 'TRADING_LOOP_NOT_READY' ? 'Автономный торговый цикл ещё не готов' : d.reason}</strong><small>Запись {d.id}</small></div><time>{new Date(d.at).toLocaleString('ru-RU')}</time></article>) : <Empty title="Решений ещё нет" text="Анализ начнётся после подключения источника рыночных данных. Каждый HOLD и SKIP будет сохранён."/>}</div>;
  return <div className="app-shell">
    <aside><a href="/" className="brand"><span className="brand-icon">M</span>MarketBrain<span className="version">0.2</span></a><div className="workspace-label">ТОРГОВОЕ ПРОСТРАНСТВО</div><nav>{navigation.map((item, i) => <button key={item} className={tab === item ? 'selected' : ''} onClick={() => setTab(item)}><span className="nav-icon">{['◫','⌕','◈','≡','⌁','◇','⚙'][i]}</span>{item}</button>)}</nav><div className="sidebar-bottom"><div className="shield">◇ <strong>Капитал под контролем</strong></div><p>Сохранение капитала важнее совершения сделки.</p><span className="sandbox-pill">SANDBOX · ВИРТУАЛЬНЫЕ СРЕДСТВА</span></div></aside>
    <div className="main-shell"><header><div className="breadcrumb">Рабочее пространство <span>/</span> <strong>{tab}</strong></div><div className="header-status"><span className="tag blue">SANDBOX</span><span className="header-market"><i/>Рынок: {market?.connection.fresh ? 'снимки данных' : 'нет свежих данных'}</span>{data && <button className="text-button" disabled={busy} onClick={async () => { await action('auth/logout', {}); setPassword(''); }}>Выйти</button>}</div></header>
    <main><div className="page-heading"><div><div className="eyebrow">MARKET INTELLIGENCE</div><h1>{tab === 'Обзор' ? 'Ваш торговый центр' : tab}</h1><p>Анализ. Решения. Контроль риска.</p></div><div className="system-status"><i className={connected ? 'green-dot' : ''}/>{connected ? 'Сервер доступен' : 'Нет связи с сервером'}</div></div>
    {error && <div role="alert" className="error">{error}<button aria-label="Закрыть сообщение" onClick={() => setError('')}>×</button></div>}
    {notice && <div role="status" className="notice">{notice}<button aria-label="Закрыть сообщение" onClick={() => setNotice('')}>×</button></div>}
    {!loaded ? <section className="panel"><Empty title="Подключаемся к MarketBrain…" text="Проверяем доступ к вашему рабочему пространству."/></section> : !data ? <section className="auth-layout"><div><span className="tag blue">SANDBOX FIRST</span><h2>Каждое решение<br/>должно быть объяснимым.</h2><p>Начните с виртуального капитала 1 000 ₽. Никаких случайных сделок, выдуманных прогнозов и доступа ИИ к деньгам.</p><div className="auth-points"><span>01 · Фактические данные</span><span>02 · Независимая проверка риска</span><span>03 · Полная история решений</span></div></div><form className="panel auth-panel" onSubmit={e => { e.preventDefault(); void action(`auth/${register ? 'register' : 'login'}`, { email, password }); setPassword(''); }}><h2>{register ? 'Создать аккаунт' : 'Вход в MarketBrain'}</h2><p>Ваше личное торговое пространство</p><label>Email<input type="email" required autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} maxLength={254}/></label><label>Пароль<input type="password" required minLength={12} maxLength={128} autoComplete={register ? 'new-password' : 'current-password'} value={password} onChange={e => setPassword(e.target.value)}/><small>Не менее 12 символов</small></label><button className="primary" disabled={busy}>{busy ? 'Подождите…' : register ? 'Создать аккаунт' : 'Войти'}</button><button type="button" className="text-button" onClick={() => { setRegister(!register); setError(''); }}>{register ? 'Уже есть аккаунт? Войти' : 'Создать новый аккаунт'}</button></form></section> : <>
    {(tab === 'Обзор' || tab === 'Портфель') && <><div className="capital-grid">{[['Общий капитал',data.portfolio.equity,'Виртуальные средства'],['Свободные деньги',data.portfolio.cash,'Доступны в Sandbox'],['Капитал в рынке',data.portfolio.invested,'Открытых позиций: 0'],['Результат торговли',null,'Сделок ещё не было']].map(([title,value,sub]) => <section className="panel stat" key={title}><span>{title}</span><strong>{value ? money(value) : '—'}</strong><small>{sub}</small></section>)}</div><section className="panel autopilot"><div className="autopilot-icon">⌁</div><div><div className="eyebrow">AUTOPILOT</div><h2>Остановлен <span className="tag amber">SAFE MODE</span></h2><p>Новые покупки заблокированы. Торговый цикл проходит разработку.</p></div><button disabled={busy || !connected} className="primary" onClick={() => void action('autopilot/start', {})}>Проверить готовность <span>↗</span></button></section>
    <div className="content-grid"><section className="panel"><PanelHeading title="Открытые позиции" badge="0"/><Empty title="Капитал остаётся свободным" text="Нет открытых позиций. При отсутствии качественного сигнала система выбирает NO TRADE."/></section><section className="panel"><PanelHeading title="Состояние системы"/><div className="system-row"><span>T-Invest</span><span className={`tag ${data.broker_connection.status === 'CONNECTED' ? 'blue' : 'amber'}`}>{brokerLabels[data.broker_connection.status] || data.broker_connection.status}</span></div><div className="system-row"><span>Рыночные данные</span><span>{data.broker_connection.fresh ? 'Снимки Sandbox' : 'Нет свежего снимка'}</span></div><div className="system-row"><span>Фоновый обработчик</span><span className={data.worker_healthy ? 'positive' : 'negative'}>{data.worker_healthy ? 'Работает' : 'Недоступен'}</span></div><div className="system-row"><span>Реальная торговля</span><span className="tag">Заблокирована</span></div><p className="panel-note">Управляйте Sandbox-подключением в настройках. Данные собираются снимками; поток котировок ещё не подключён.</p></section></div><section className="panel"><PanelHeading title="Текущие решения" badge={`${data.decisions.length}`}/>{decisions}</section></>}
    {tab === 'Рынок' && <MarketPanel market={market}/>}
    {tab === 'Обзор' && <section className="panel"><PanelHeading title="Последние события"/>{activity}</section>}
    {tab === 'Журнал решений' && <section className="panel"><PanelHeading title="Решения и основания"/>{decisions}</section>}
    {tab === 'Live Brain' && <section className="panel"><PanelHeading title="Факты и действия системы" badge="AUDIT"/>{activity}<p className="panel-note">Отображаются сохранённые события. Обновление состояния — каждые 30 секунд.</p></section>}
    {tab === 'Управление риском' && <><section className="panel"><PanelHeading title="Лимиты Sandbox"/>{[['Риск одной сделки',data.risk.trade],['Максимальная доля компании',data.risk.position],['Общий капитал в рынке',data.risk.exposure],['Дневной лимит потерь',data.risk.daily_loss],['Максимальная просадка',data.risk.drawdown]].map(([label,value]) => <div className="system-row" key={label}><span>{label}</span><strong>{pct(value)}</strong></div>)}<p className="panel-note">Лимиты задаются серверной конфигурацией. Плечо, шорты и автономное увеличение риска запрещены.</p></section><section className="panel"><PanelHeading title="Причины блокировки"/>{data.blockers.map(b => <div className="system-row" key={b}><span>{b}</span><span className="tag amber">BLOCK</span></div>)}</section></>}
    {tab === 'Настройки' && <><BrokerPanel connection={data.broker_connection} busy={busy || !connected} action={action}/><section className="panel"><PanelHeading title="Виртуальный капитал"/><p className="panel-note">Изменение баланса сохраняется в журнале. Средства существуют только в Sandbox.</p><form className="balance-form" onSubmit={e => { e.preventDefault(); void action('sandbox/balance', { amount: balance }); }}><label>Сумма, ₽<input required type="number" min="0.01" max="100000000" step="0.01" value={balance} onChange={e => setBalance(e.target.value)}/></label><button className="primary" disabled={busy || !connected}>Сохранить баланс</button></form></section><section className="panel"><PanelHeading title="Аккаунт"/><div className="system-row"><span>Email</span><span>{data.user.email}</span></div><div className="system-row"><span>Роль</span><span className="tag">{data.user.role}</span></div><div className="system-row"><span>Режим</span><span>SANDBOX</span></div></section></>}
    <footer><span>MarketBrain · Sandbox Data v0.2</span><span>{lastUpdate ? `Обновлено ${lastUpdate.toLocaleTimeString('ru-RU')}` : 'Ожидание данных'} · NO TRADE при неопределённости</span></footer></>}
    </main></div></div>;
}

function Empty({ title, text }: { title: string; text: string }) { return <div className="empty"><span>◇</span><h3>{title}</h3><p>{text}</p></div>; }
function PanelHeading({ title, badge }: { title: string; badge?: string }) { return <div className="panel-heading"><h2>{title}</h2>{badge && <span className="tag">{badge}</span>}</div>; }
