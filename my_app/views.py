import re
import uuid
from io import BytesIO

import qrcode
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q
from django.http import HttpResponse, HttpResponseNotFound
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from my_app.models import Candidate, Nomination, Vote

DEVICE_COOKIE = 'voter_id'
COOKIE_MAX_AGE = 60 * 60 * 24 * 400
DEVICE_ID_RE = re.compile(r'^[a-f0-9]{32}$')


def home(request):
    nominations = Nomination.objects.all()
    return render(request, 'index.html', {'nominations': nominations})


def _vote_totals(nomination):
    if nomination.voting_status() == 'waiting':
        return {}
    return {
        row['candidate']: row['total']
        for row in nomination.votes_in_window().values('candidate').annotate(total=Count('id'))
    }


def _voting_context(nomination):
    status = nomination.voting_status()
    winner_ids = []
    if status == 'closed':
        winner_ids, totals = nomination.announce_winners()
    else:
        totals = _vote_totals(nomination)
    candidates = list(nomination.candidates.all())
    winners = []
    for candidate in candidates:
        candidate.window_votes = totals.get(candidate.id, 0)
        if candidate.id in winner_ids:
            winners.append(candidate)
    if status != 'waiting':
        candidates.sort(key=lambda item: (-item.window_votes, item.full_name or ''))
    max_votes = max((item.window_votes for item in candidates), default=0)
    return {
        'status': status,
        'candidates': candidates,
        'winners': winners,
        'totals': totals,
        'max_votes': max_votes,
        'ends_at': nomination.voting_ends_at,
    }


def nomination_detail(request, slug):
    nomination = get_object_or_404(Nomination, slug=slug)
    host = request.get_host().split(':')[0]
    context = _voting_context(nomination)
    context.update({
        'nomination': nomination,
        'local_only': host in {'127.0.0.1', 'localhost', '::1'},
    })
    return render(request, 'nomination.html', context)


@require_POST
def start_voting(request, slug):
    nomination = get_object_or_404(Nomination, slug=slug)
    if nomination.voting_started_at is None:
        nomination.voting_started_at = timezone.now()
        nomination.save(update_fields=['voting_started_at'])
    return redirect('nomination', slug=nomination.slug)


def nomination_qr(request, slug):
    nomination = get_object_or_404(Nomination, slug=slug)
    if nomination.voting_status() != 'open':
        return HttpResponseNotFound()
    vote_url = request.build_absolute_uri(reverse('vote', args=[nomination.slug]))
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    code.add_data(vote_url)
    code.make(fit=True)
    image = code.make_image(fill_color='#0d3f2e', back_color='#ffffff')
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    response = HttpResponse(buffer.getvalue(), content_type='image/png')
    response['Cache-Control'] = 'no-store'
    return response


def _valid_device_id(value):
    return value if DEVICE_ID_RE.match(value or '') else ''


def _device_id(request):
    cookie_id = _valid_device_id(request.COOKIES.get(DEVICE_COOKIE, ''))
    if cookie_id:
        return cookie_id
    posted_id = _valid_device_id(request.POST.get('device_id', ''))
    if posted_id:
        return posted_id
    return uuid.uuid4().hex


def _client_ip(request):
    return request.META.get('REMOTE_ADDR') or None


def _remember_device(response, device_id):
    response.set_cookie(
        DEVICE_COOKIE,
        device_id,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite='Lax',
        path='/',
    )
    return response


def _existing_vote(nomination, device_id, ip):
    query = Q(device_id=device_id)
    if ip:
        query |= Q(ip_address=ip)
    return (
        Vote.objects.filter(query, nomination=nomination)
        .select_related('candidate')
        .first()
    )


@require_http_methods(['GET', 'POST'])
def vote(request, slug):
    nomination = get_object_or_404(Nomination, slug=slug)
    voting = _voting_context(nomination)
    candidates = voting['candidates']
    status = voting['status']
    device_id = _device_id(request)
    ip = _client_ip(request)
    existing = _existing_vote(nomination, device_id, ip)
    error = None

    if existing is not None:
        device_id = existing.device_id

    if request.method == 'POST' and existing is None and status != 'open':
        error = 'Ovoz berish vaqti tugagan.' if status == 'closed' else 'Ovoz berish hali boshlanmagan.'

    if request.method == 'POST' and existing is None and status == 'open':
        candidate = next(
            (item for item in candidates if str(item.pk) == request.POST.get('candidate')),
            None,
        )
        if candidate is None:
            error = 'Nomzodni tanlang.'
        else:
            try:
                with transaction.atomic():
                    existing = Vote.objects.create(
                        candidate=candidate,
                        nomination=nomination,
                        device_id=device_id,
                        ip_address=ip,
                    )
                    existing.candidate = candidate
                    Candidate.objects.filter(pk=candidate.pk).update(votes=F('votes') + 1)
            except IntegrityError:
                existing = _existing_vote(nomination, device_id, ip)
                if existing is not None:
                    device_id = existing.device_id

    response = render(request, 'vote.html', {
        'nomination': nomination,
        'candidates': candidates,
        'existing': existing,
        'device_id': device_id,
        'error': error,
        'status': status,
        'winners': voting['winners'],
        'totals': voting['totals'],
        'max_votes': voting['max_votes'],
    })
    return _remember_device(response, device_id)
