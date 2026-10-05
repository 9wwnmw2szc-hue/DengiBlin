'use client';
import { useEffect, useState } from 'react';

export type BrokerStatus = {
  status: string; mode: string; accounts: { id: string; name: string; status: string; access: string }[];
  account_id: string | null; watchlist: string[]; last_sync_at: string | null;
  last_error: string | null; fresh: boolean;
};
export type MarketData = {
  connection: BrokerStatus;
  instruments: { uid: string; ticker: string; name: string; lot: number; price: string | null;
    quote_at: string | null; quote_id: string | null; age_seconds: number | null; fresh: boolean;
    status: { status?: string; api_available?: boolean } }[];
  snapshot: { id: string; at: string; portfolio: { equity: string | null; currency: string | null;
    positions: { uid: string; quantity: string; price: string; currency: string }[] };
    balances: { money: { currency: string; amount: string }[]; blocked: { currency: string; amount: string }[] };
    orders: { id: string; uid: string; state: string; direction: string; lots: number; filled_lots: number }[];
    missing_tickers: string[] } | null;
};
type Action = (path: string, body: unknown) => Promise<void>;
export const brokerLabels: Record<string, string> = { NOT_CONNECTED:'Не подключён', ACCOUNT_REQUIRED:'Выберите счёт', PENDING_SYNC:'Ожидает обновления', CONNECTED:'Подключён', ERROR:'Ошибка подключения' };
const failures: Record<string, string> = { TOKEN_REJECTED:'Брокер отклонил токен', BROKER_UNAVAILABLE:'Брокер недоступен', RATE_LIMIT:'Достигнут лимит запросов', ACCOUNT_UNAVAILABLE:'Счёт больше недоступен', SECRET_UNAVAILABLE:'Серверное хранилище недоступно', WATCHLIST_UNAVAILABLE:'Инструменты списка не найдены', MALFORMED_RESPONSE:'Данные не прошли проверку', INCONSISTENT_QUOTE:'Обнаружено противоречие в котировках' };
const time = (value: string) => new Date(value).toLocaleString('ru-RU');
const price = (value: string) => Number(value).toLocaleString('ru-RU', { maximumFractionDigits: 9 });

export function BrokerPanel({ connection, busy, action }: { connection: BrokerStatus; busy: boolean; action: Action }) {
  const [account, setAccount] = useState('');
  const [tickers, setTickers] = useState('');
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  useEffect(() => { setAccount(connection.account_id || ''); setTickers(connection.watchlist.join(', ')); }, [connection.account_id, connection.watchlist.join(',')]);
  const active = connection.status !== 'NOT_CONNECTED';
  return <section className="panel"><div className="panel-heading"><h2>T-Invest Sandbox</h2><span className={`tag ${connection.status === 'CONNECTED' ? 'blue' : 'amber'}`}>{brokerLabels[connection.status] || connection.status}</span></div>
    {!active ? <div className="connection-intro"><h3>Подключите источник рыночных данных</h3><p>Добавьте Sandbox-токен на сервере по инструкции. После проверки здесь появятся ваши виртуальные счета.</p><a href="https://github.com/9wwnmw2szc-hue/DengiBlin/blob/main/docs/TINVEST_SETUP.md" target="_blank" rel="noreferrer" className="primary">Инструкция подключения ↗</a><p className="panel-note">Токен не вводится в браузере и не отправляется в чат. Реальная торговля заблокирована.</p></div> : <>
    {connection.last_error && <div role="status" className="connection-warning">{failures[connection.last_error] || 'Подключение требует проверки'}. Предыдущие данные сохраняются как история и не разрешают торговлю.</div>}
    <form className="broker-form" onSubmit={e => { e.preventDefault(); void action('broker/account',{ account_id:account }); }}><label>Виртуальный счёт<select required value={account} onChange={e => setAccount(e.target.value)}><option value="">Выберите Sandbox-счёт</option>{connection.accounts.filter(a => a.status === 'ACCOUNT_STATUS_OPEN').map(a => <option key={a.id} value={a.id}>{a.name} · {a.id}</option>)}</select></label><button className="primary" disabled={busy || !account}>Выбрать счёт</button></form>
    {!connection.accounts.length && <p className="panel-note">Нет доступных Sandbox-счетов. Создайте виртуальный счёт у брокера и повторите проверку подключения.</p>}
    <form className="broker-form" onSubmit={e => { e.preventDefault(); void action('broker/watchlist',{ tickers:tickers.split(',').map(t => t.trim()).filter(Boolean) }); }}><label>Список наблюдения · до 5 акций<input value={tickers} onChange={e => setTickers(e.target.value)} placeholder="SBER, GAZP" required maxLength={100}/></label><button className="primary" disabled={busy}>Сохранить список</button></form>
    <div className="system-row"><span>Последний полный снимок</span><span>{connection.last_sync_at ? time(connection.last_sync_at) : 'Ещё не загружен'}</span></div>
    <div className="broker-actions"><button className="primary" disabled={busy || !connection.account_id} onClick={() => void action('broker/sync',{})}>Обновить данные</button><button className="text-button" disabled={busy} onClick={() => void action('broker/validate',{})}>Проверить подключение</button><button className="text-button danger-text" disabled={busy} onClick={() => setConfirmDisconnect(true)}>Отключить</button></div>
    {confirmDisconnect && <div className="connection-warning"><p>Отключить Sandbox? Загрузка данных остановится, локальная копия токена будет удалена. Для отзыва токена у брокера используйте настройки T-Invest.</p><div className="broker-actions"><button disabled={busy} className="primary" onClick={async () => { await action('broker/disconnect',{}); setConfirmDisconnect(false); }}>Отключить подключение</button><button className="text-button" onClick={() => setConfirmDisconnect(false)}>Отмена</button></div></div>}
    <p className="panel-note">Снимки обновляются примерно раз в 5 минут. Это сбор истории, а не поток котировок для торговли. Заменить токен можно на сервере по <a href="https://github.com/9wwnmw2szc-hue/DengiBlin/blob/main/docs/TINVEST_SETUP.md" target="_blank" rel="noreferrer">инструкции</a>.</p></>}
  </section>;
}

export function MarketPanel({ market }: { market: MarketData | null }) {
  const [selected, setSelected] = useState<string | null>(null);
  return <><section className="panel"><div className="panel-heading"><h2>Акции в списке наблюдения</h2><span className="tag blue">T-INVEST · SANDBOX</span></div><p className="panel-note market-note">Только полученные от брокера данные. Возраст котировки считается по времени последней сделки, а не по времени загрузки.</p>
    {!market?.instruments.length ? <div className="empty"><span>◇</span><h3>Рыночных данных пока нет</h3><p>Подключите Sandbox, выберите счёт и запросите обновление в настройках.</p></div> : <div className="market-cards">{market.instruments.map(i => <button className={`market-card ${selected === i.uid ? 'market-selected' : ''}`} onClick={() => setSelected(i.uid)} key={i.uid}><div className="market-card-heading"><strong>{i.ticker}</strong><span className={`tag ${i.fresh ? 'blue' : 'amber'}`}>{i.fresh ? 'Свежая цена' : 'Устаревшая / нет цены'}</span></div><p>{i.name}</p><div className="market-price">{i.price ? `${price(i.price)} ₽` : '—'}</div><small>Лот: {i.lot} акций</small><small>{i.quote_at ? `Последняя сделка: ${time(i.quote_at)}` : 'Нет подтверждённой котировки'}</small><div className="market-status">{i.status.status === 'SECURITY_TRADING_STATUS_NORMAL_TRADING' ? 'Торговый статус: основная сессия' : `Торговый статус: ${i.status.status || 'неизвестен'}`}</div></button>)}</div>}
    {market?.snapshot?.missing_tickers.length ? <p className="panel-note">Не найдены среди доступных рублёвых акций TQBR: {market.snapshot.missing_tickers.join(', ')}.</p> : null}
  </section>{selected && <CandlePanel instrument={selected}/>}
  {market?.snapshot && <section className="panel"><div className="panel-heading"><h2>Sandbox-счёт у брокера · только чтение</h2><span className="tag">{market.connection.fresh ? 'СНИМОК' : 'ИСТОРИЯ'}</span></div><div className="system-row"><span>Стоимость портфеля</span><strong>{market.snapshot.portfolio.equity && market.snapshot.portfolio.currency === 'rub' ? `${price(market.snapshot.portfolio.equity)} ₽` : 'Нет подтверждённой суммы в ₽'}</strong></div><div className="system-row"><span>Позиций у брокера</span><span>{market.snapshot.portfolio.positions.length}</span></div><div className="system-row"><span>Активных заявок у брокера</span><span>{market.snapshot.orders.length}</span></div>{market.snapshot.balances.money.map((m,i) => <div className="system-row" key={i}><span>Денежная позиция · {m.currency?.toUpperCase()}</span><span>{price(m.amount)}</span></div>)}<p className="panel-note">Получено {time(market.snapshot.at)}. Снимок {market.snapshot.id}. Этот счёт отделён от локального виртуального баланса MarketBrain.</p></section>}</>;
}

type Candle = { id: string; at: string; open: string; high: string; low: string; close: string; volume: string; complete: boolean };
function CandlePanel({ instrument }: { instrument: string }) {
  const [history, setHistory] = useState<{ticker:string; candles:Candle[]} | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController(); setHistory(null); setError(false);
    fetch(`/api/market/${encodeURIComponent(instrument)}/candles`,{signal:controller.signal}).then(async r => {
      if (!r.ok) throw new Error(); return r.json();
    }).then(setHistory).catch(e => { if (e.name !== 'AbortError') setError(true); });
    return () => controller.abort();
  },[instrument]);
  return <section className="panel"><div className="panel-heading"><h2>Исторические свечи {history?.ticker}</h2><span className="tag">1H · OHLCV</span></div>{error ? <p className="panel-note">История недоступна. Данные не подменяются.</p> : !history ? <p className="panel-note">Загрузка истории…</p> : !history.candles.length ? <p className="panel-note">Брокер ещё не вернул свечи для этого инструмента.</p> : <div className="candle-scroll"><table><thead><tr><th>Время</th><th>Открытие</th><th>Макс.</th><th>Мин.</th><th>Закрытие</th><th>Объём, лоты</th><th>Состояние</th></tr></thead><tbody>{history.candles.slice(-24).reverse().map(c => <tr key={c.id}><td>{time(c.at)}</td><td>{price(c.open)}</td><td>{price(c.high)}</td><td>{price(c.low)}</td><td>{price(c.close)}</td><td>{price(c.volume)}</td><td>{c.complete ? 'Завершена' : 'Формируется'}</td></tr>)}</tbody></table></div>}<p className="panel-note">Формирующаяся свеча хранится отдельно по признаку завершённости и не должна участвовать в сигналах до закрытия.</p></section>;
}
