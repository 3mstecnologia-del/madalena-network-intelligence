from __future__ import annotations

from datetime import datetime

from app.cdr.models import CdrDashboard, CdrCanonicalCall


def _fmt_seconds(value: int | None) -> str:
    value = int(value or 0)
    h, rem = divmod(value, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _bar(values: list[dict], label_key: str, value_key: str, width: int = 320) -> str:
    max_val = max((int(v[value_key]) for v in values), default=1)
    rows = []
    for item in values:
        val = int(item[value_key])
        pct = 0 if max_val == 0 else round((val / max_val) * 100, 1)
        rows.append(
            f"<div class='bar-row'><div class='bar-label'>{item[label_key]}</div>"
            f"<div class='bar-track'><div class='bar-fill' style='width:{pct}%' /></div>"
            f"<div class='bar-value'>{val}</div></div>"
        )
    return "".join(rows)


def dashboard_html(d: CdrDashboard) -> str:
    hourly = "".join(
        f"<div class='hour'><span>{row['hour']:02d}h</span><strong>{row['count']}</strong></div>"
        for row in d.hourly_distribution
    )
    calls_rows = "".join(
        f"<tr><td>{c.first_seen.strftime('%d/%m %H:%M')}</td><td>{c.direction}</td><td>{c.status}</td><td>{c.source or ''}</td><td>{c.destination or ''}</td><td>{c.extension or ''}</td><td>{c.trunk or ''}</td><td>{c.legs}</td><td>{_fmt_seconds(c.billsec)}</td><td>{_fmt_seconds(c.duration)}</td><td>{c.linkedid}</td></tr>"
        for c in d.canonical_calls
    )
    return f"""
    <section class='report-summary'>
      <div class='hero'>
        <h1>CDR LeSante</h1>
        <p>Relatório canônico read-only em {d.period_start.strftime('%d/%m/%Y')} — {d.period_end.strftime('%d/%m/%Y')}</p>
      </div>
      <div class='kpis'>
        <article><span>Total de chamadas</span><strong>{d.total_calls}</strong></article>
        <article><span>Recebidas</span><strong>{d.inbound_calls}</strong></article>
        <article><span>Realizadas</span><strong>{d.outbound_calls}</strong></article>
        <article><span>Atendidas</span><strong>{d.answered_calls}</strong></article>
        <article><span>Perdidas</span><strong>{d.missed_calls}</strong></article>
        <article><span>Taxa de atendimento</span><strong>{d.answer_rate:.1f}%</strong></article>
        <article><span>Duração total</span><strong>{_fmt_seconds(d.total_duration)}</strong></article>
        <article><span>Billsec total</span><strong>{_fmt_seconds(d.total_billsec)}</strong></article>
      </div>
      <div class='grid-2'>
        <section><h3>Ramal</h3>{_bar(d.extensions, 'label', 'count')}</section>
        <section><h3>Origens</h3>{_bar(d.sources, 'label', 'count')}</section>
        <section><h3>Destinos</h3>{_bar(d.destinations, 'label', 'count')}</section>
        <section><h3>Distribuição por horário</h3><div class='hours'>{hourly}</div></section>
      </div>
      <section>
        <h3>Chamadas canônicas</h3>
        <table><thead><tr><th>Início</th><th>Direção</th><th>Status</th><th>Origem</th><th>Destino</th><th>Ramal</th><th>Tronco</th><th>Legs</th><th>Billsec</th><th>Duração</th><th>LinkedID</th></tr></thead><tbody>{calls_rows}</tbody></table>
      </section>
    </section>
    """


def report_html(d: CdrDashboard, title: str, filters: dict[str, str]) -> str:
    filters_html = "".join(f"<li><b>{k}</b>: {v}</li>" for k, v in filters.items() if v)
    rows = "".join(
        f"<tr><td>{c.first_seen.strftime('%d/%m/%Y %H:%M:%S')}</td><td>{c.linkedid}</td><td>{c.direction}</td><td>{c.status}</td><td>{c.source or ''}</td><td>{c.destination or ''}</td><td>{c.extension or ''}</td><td>{c.trunk or ''}</td><td>{c.legs}</td><td>{_fmt_seconds(c.billsec)}</td><td>{_fmt_seconds(c.duration)}</td></tr>"
        for c in d.canonical_calls
    )
    return f"""
    <html lang='pt-BR'>
    <head>
      <meta charset='utf-8' />
      <meta name='viewport' content='width=device-width, initial-scale=1' />
      <title>{title}</title>
      <style>
        body {{ font-family: Inter, system-ui, sans-serif; margin: 0; padding: 24px; background: #0f172a; color: #e2e8f0; }}
        .card {{ background: #111827; border: 1px solid #243044; border-radius: 16px; padding: 20px; margin-bottom: 18px; }}
        .kpis {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(160px,1fr)); gap: 12px; }}
        .kpis div {{ background:#0b1220; border:1px solid #243044; border-radius:12px; padding:12px; }}
        .kpis span {{ color:#94a3b8; display:block; font-size:12px; }}
        .kpis strong {{ font-size:24px; }}
        table {{ width:100%; border-collapse: collapse; font-size: 13px; }}
        th, td {{ border-bottom:1px solid #243044; padding:8px; text-align:left; }}
        h1,h2,h3 {{ margin: 0 0 12px 0; }}
        ul {{ margin: 0; padding-left: 18px; }}
        .hours {{ display:grid; grid-template-columns: repeat(6,1fr); gap: 8px; }}
        .hour {{ background:#0b1220; border:1px solid #243044; border-radius:10px; padding:10px; text-align:center; }}
      </style>
    </head>
    <body>
      <div class='card'>
        <h1>{title}</h1>
        <p>Gerado em {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC · período {d.period_start.strftime('%d/%m/%Y %H:%M')} → {d.period_end.strftime('%d/%m/%Y %H:%M')}</p>
        <ul>{filters_html}</ul>
      </div>
      <div class='card'>
        <div class='kpis'>
          <div><span>Total</span><strong>{d.total_calls}</strong></div>
          <div><span>Recebidas</span><strong>{d.inbound_calls}</strong></div>
          <div><span>Realizadas</span><strong>{d.outbound_calls}</strong></div>
          <div><span>Atendidas</span><strong>{d.answered_calls}</strong></div>
          <div><span>Perdidas</span><strong>{d.missed_calls}</strong></div>
          <div><span>Taxa</span><strong>{d.answer_rate:.1f}%</strong></div>
        </div>
      </div>
      <div class='card'>
        <h2>Resumo executivo</h2>
        <p>O relatório foi consolidado por <b>linkedid</b>, evitando dupla contagem de legs, canais Local/, filas e transferências.</p>
      </div>
      <div class='card'>
        <h2>Detalhamento</h2>
        <table>
          <thead><tr><th>Início</th><th>LinkedID</th><th>Direção</th><th>Status</th><th>Origem</th><th>Destino</th><th>Ramal</th><th>Tronco</th><th>Legs</th><th>Billsec</th><th>Duração</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </body>
    </html>
    """
