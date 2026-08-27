"""Stub mínimo de EventKit para testar a lógica do unidate fora do macOS."""
import itertools

EKEntityTypeEvent = 0
EKSpanThisEvent = 0
EKEventAvailabilityBusy = 0
EKEventAvailabilityFree = 1
EKEventStatusCanceled = 3
EKParticipantStatusDeclined = 3
EKCalendarTypeSubscription = 3
EKCalendarTypeBirthday = 4
EKSourceTypeLocal = 0
EKSourceTypeExchange = 1
EKSourceTypeCalDAV = 2

_ids = itertools.count(1)


class Source:
    def __init__(self, title, stype=EKSourceTypeExchange):
        self._t, self._st = title, stype

    def title(self):
        return self._t

    def sourceType(self):
        return self._st


class Calendar:
    def __init__(self, ident, title, source, ctype=1, writable=True,
                 stype=EKSourceTypeExchange):
        self._id, self._t, self._s, self._ct, self._w = ident, title, Source(source, stype), ctype, writable

    def calendarIdentifier(self):
        return self._id

    def title(self):
        return self._t

    def source(self):
        return self._s

    def type(self):
        return self._ct

    def allowsContentModifications(self):
        return self._w


class Attendee:
    def __init__(self, current_user=False, status=2):
        self._cu, self._st = current_user, status

    def isCurrentUser(self):
        return self._cu

    def participantStatus(self):
        return self._st


class EKEvent:
    def __init__(self, store=None):
        self._store = store
        self._id = "evt-%d" % next(_ids)
        # no EventKit real este identificador persiste entre dispositivos e
        # entre instancias do store, ao contrario de eventIdentifier
        self._ext = "ext-%s" % self._id
        self._cal = None
        self._title = ""
        self._start = None
        self._end = None
        self._avail = EKEventAvailabilityBusy
        self._notes = None
        self._allday = False
        self._status = 1
        self._attendees = []
        self._alarms = None

    @classmethod
    def eventWithEventStore_(cls, store):
        return cls(store)

    # getters
    def eventIdentifier(self):
        return self._id

    def calendarItemIdentifier(self):
        return self._id

    def calendarItemExternalIdentifier(self):
        return self._ext

    def calendar(self):
        return self._cal

    def title(self):
        return self._title

    def startDate(self):
        return self._start

    def endDate(self):
        return self._end

    def availability(self):
        return self._avail

    def notes(self):
        return self._notes

    def isAllDay(self):
        return self._allday

    def status(self):
        return self._status

    def attendees(self):
        return self._attendees

    # setters
    def setCalendar_(self, c):
        self._cal = c

    def setTitle_(self, t):
        self._title = t

    def setStartDate_(self, d):
        self._start = d

    def setEndDate_(self, d):
        self._end = d

    def setAvailability_(self, a):
        self._avail = a

    def setNotes_(self, n):
        self._notes = n

    def setAllDay_(self, v):
        self._allday = v

    def alarms(self):
        return self._alarms

    def setAlarms_(self, a):
        self._alarms = a


class _Predicate:
    def __init__(self, start, end, cals):
        self.start, self.end, self.cals = start, end, cals


class EKEventStore:
    calendars = []
    events = []

    def __init__(self):
        pass

    @classmethod
    def alloc(cls):
        return cls

    @classmethod
    def init(cls):
        return cls()

    def requestFullAccessToEventsWithCompletion_(self, handler):
        handler(True, None)

    def requestAccessToEntityType_completion_(self, t, handler):
        handler(True, None)

    def calendarsForEntityType_(self, t):
        return list(EKEventStore.calendars)

    def predicateForEventsWithStartDate_endDate_calendars_(self, start, end, cals):
        return _Predicate(start.timeIntervalSince1970(), end.timeIntervalSince1970(), cals)

    def eventsMatchingPredicate_(self, pred):
        ids = {c.calendarIdentifier() for c in (pred.cals or EKEventStore.calendars)}
        out = []
        for e in EKEventStore.events:
            if e.calendar() is None or e.calendar().calendarIdentifier() not in ids:
                continue
            s = e.startDate().timeIntervalSince1970()
            en = e.endDate().timeIntervalSince1970()
            if en >= pred.start and s <= pred.end:
                out.append(e)
        return out

    def eventWithIdentifier_(self, ident):
        for e in EKEventStore.events:
            if e.eventIdentifier() == ident:
                return e
        return None

    def saveEvent_span_commit_error_(self, ev, span, commit, err):
        if ev not in EKEventStore.events:
            EKEventStore.events.append(ev)
        return (True, None)

    def removeEvent_span_commit_error_(self, ev, span, commit, err):
        if ev in EKEventStore.events:
            EKEventStore.events.remove(ev)
            return (True, None)
        return (False, "not found")
