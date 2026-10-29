from django.contrib import admin

from my_app.models import Candidate, Nomination, Vote


class CandidateInline(admin.TabularInline):
    model = Candidate
    extra = 1
    fields = ('full_name', 'photo', 'description', 'votes', 'is_winner')


@admin.register(Nomination)
class NominationAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'voting_started_at')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [CandidateInline]


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'nomination', 'votes', 'is_winner')
    list_filter = ('nomination',)


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ('nomination', 'candidate', 'ip_address', 'device_id', 'created_at')
    list_filter = ('nomination',)
