"""Book both daily posts early; each scheduled wake-up can repair a missed prepare."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from .config import track_config


def maintain(c, entries, channel, factory, now):
    if not c.get('daily_enabled',True):
        return ['Daily preparation is paused']
    local=now.astimezone(ZoneInfo(c['timezone']))
    if c.get('schedule_effective_date') and local.date()<date.fromisoformat(c['schedule_effective_date']):
        return ['New schedule is not effective yet; only delivery verification runs today']
    prep_hour,prep_minute=map(int,c.get('daily_prepare_time','06:00').split(':'))
    if (local.hour,local.minute)<(prep_hour,prep_minute):
        return [f"Before daily preparation time ({c.get('daily_prepare_time','06:00')} local)"]
    results=[];failures=[]
    for post in c['daily_posts']:
        kind=post['kind'];day=local.date().isoformat()
        key=f'{channel}:{day}:{kind}'
        entry=entries.get(key)
        legacy=entries.get(f'{channel}:{day}')
        if entry and entry['status'] in ('accepted','sent'):
            results.append(f'{kind}: already booked or sent');continue
        if legacy and legacy['status'] in ('accepted','sent') and legacy.get('post_kind','cinema')==kind:
            results.append(f'{kind}: legacy post already booked or sent');continue
        hour,minute=map(int,post['time'].split(':'))
        due=datetime(local.year,local.month,local.day,hour,minute,tzinfo=local.tzinfo)
        if local<due and due-local<timedelta(minutes=c['prepare_lead_minutes']):
            results.append(f'{kind}: too close to scheduled time; next wake-up will publish today immediately')
            continue
        # A delayed wake-up resumes today's existing journal, not a duplicate or tomorrow's slot.
        try:
            results.append(factory(track_config(c,kind)).prepare(publish_now=local>=due))
        except (RuntimeError,ValueError) as exc:
            failures.append(f'{kind}: {exc}')
    if failures:
        raise RuntimeError('; '.join(failures))
    return results
