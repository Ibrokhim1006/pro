from datetime import timedelta

from django.db import models
from django.db.models import Count
from django.utils import timezone

VOTING_DURATION = timedelta(minutes=5)


class Nomination(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    voting_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Bo‘sh bo‘lsa ovoz yopiq. To‘ldirilsa shu paytdan 5 daqiqa ochiladi.',
    )

    class Meta:
        verbose_name = 'Номинация'
        verbose_name_plural = 'Номинация'

    def __str__(self):
        return self.name

    @property
    def voting_ends_at(self):
        if not self.voting_started_at:
            return None
        return self.voting_started_at + VOTING_DURATION

    def voting_status(self, now=None):
        now = now or timezone.now()
        if not self.voting_started_at:
            return 'waiting'
        if now < self.voting_ends_at:
            return 'open'
        return 'closed'

    def votes_in_window(self):
        if not self.voting_started_at:
            return Vote.objects.none()
        return Vote.objects.filter(
            nomination=self,
            created_at__gte=self.voting_started_at,
            created_at__lt=self.voting_ends_at,
        )

    def announce_winners(self):
        totals = {
            row['candidate']: row['total']
            for row in self.votes_in_window().values('candidate').annotate(total=Count('id'))
        }
        best = max(totals.values(), default=0)
        winner_ids = [candidate_id for candidate_id, total in totals.items() if total == best and best > 0]
        self.candidates.update(is_winner=False)
        if winner_ids:
            self.candidates.filter(id__in=winner_ids).update(is_winner=True)
        return winner_ids, totals
    
class Candidate(models.Model):
    nomination = models.ForeignKey(Nomination, on_delete=models.CASCADE, related_name='candidates', null=True, blank=True)
    full_name = models.CharField(max_length=100, null=True, blank=True)
    photo = models.ImageField(upload_to='candidates/', null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    votes = models.IntegerField(default=0)
    is_winner = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Участник'
        verbose_name_plural = 'Участники'

    def __str__(self):
        return self.full_name


class Vote(models.Model):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='vote_records', null=True, blank=True)
    nomination = models.ForeignKey(Nomination, on_delete=models.CASCADE, related_name='votes')
    device_id = models.CharField(max_length=64)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Голос'
        verbose_name_plural = 'Голоса'
        constraints = [
            models.UniqueConstraint(
                fields=['nomination', 'device_id'],
                name='one_vote_per_device_per_nomination',
            ),
            models.UniqueConstraint(
                fields=['nomination', 'ip_address'],
                name='one_vote_per_ip_per_nomination',
            ),
        ]
        


