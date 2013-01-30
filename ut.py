# Universal Translator base classes
# (c) krvss 2011-2013

from utils import *

# Base class for all communicable objects
class Abstract(object):

    # The way to send the abstract a message
    def parse(self, *message, **context):
        return None


# Notion is an abstract with name
class Notion(Abstract):
    def __init__(self, name):
        super(Notion, self).__init__()
        self.name = name

    def __str__(self):
        if self.name:
            return '"%s"' % self.name

    def __repr__(self):
        return self.__str__()


# Relation is a connection between one or more abstracts: subject -> object
class Relation(Abstract):
    def __init__(self, subject, object):
        super(Relation, self).__init__()
        self._object = self._subject = None

        self.subject = subject
        self.object = object

    def connect(self, value, target):
        old_value = getattr(self, target)

        if old_value == value:
            return

        # Disconnect old one
        if old_value:
            old_value.parse('un_relate', **{'from': self})

        setattr(self, '_' + target, value)

        # Connect new one
        if value:
            value.parse('relate', **{'from': self})

    @property
    def subject(self):
        return self._subject

    @subject.setter
    def subject(self, value):
        self.connect(value, 'subject')

    @property
    def object(self):
        return self._object

    @object.setter
    def object(self, value):
        self.connect(value, 'object')

    def __str__(self):
        return '<%s - %s>' % (self.subject, self.object)

    def __repr__(self):
        return self.__str__()


# Value notion is notion that returns custom value
class ValueNotion(Notion):
    def __init__(self, name, value):
        super(ValueNotion, self).__init__(name)
        self.value = value

    def parse(self, *message, **context):
        return self.value


# Function notion is notion that can callback custom function
class FunctionNotion(Notion):
    def __init__(self, name, function):
        super(FunctionNotion, self).__init__(name)
        self.function = function if callable(function) else None

    def parse(self, *message, **context):
        return self.function(self, *message, **context) if callable(self.function) else None


# Complex notion is a notion that relates with other notions (objects)
class ComplexNotion(Notion):
    def __init__(self, name, relation = None):
        super(ComplexNotion, self).__init__(name)
        self._relations = []

        self.relate(relation)

    def relate(self, relation):
        if isinstance(relation, Relation) and relation.subject == self \
           and (relation not in self._relations):
            self._relations.append(relation)

    def un_relate(self, relation):
        if relation in self._relations:
            self._relations.remove(relation)

    def parse(self, *message, **context):
        reply = super(ComplexNotion, self).parse(*message, **context)

        if not reply:
            if message:
                # This abstract knows only Relate and Unrelate messages
                if message[0] == 'relate':
                    self.relate(context.get('from'))
                    return True

                elif message[0] == 'un_relate':
                    self.un_relate(context.get('from'))
                    return True

             # Returning copy of relation list by default, not using a list if there is only one
            if self._relations:
                return self._relations[0] if len(self._relations) == 1 else list(self._relations)


# Next relation is just a simple sequence relation
class NextRelation(Relation):
    def parse(self, *message, **context):
        return self.object


# Selective notion: complex notion that can consist of one of its objects
class SelectiveNotion(ComplexNotion):
    def parse(self, *message, **context):
        if context.get('state'):
            if context.get('errors'):
                cases = context['state']['cases']

                if cases:
                    case = cases.pop(0) # Try another case

                    # Pop context and update state, then try another case and come back here
                    return ['pop_context', 'forget_context', {'set_state': {'cases': cases}},
                            'push_context', case, self]
                else:
                    return ['forget_context', 'clear_state', 'error']
            else:
                return ['forget_context', 'clear_state'] # Everything is ok, forget the past

        reply = super(SelectiveNotion, self).parse(*message, **context)

        if not isinstance(reply, list):
            return reply

        case = reply.pop(0)
        return ['push_context', {'set_state': {'cases': reply}},
                case, self] # Try first one


# Conditional relation is a condition to go further if text starts with sequence
class ConditionalRelation(Relation):
    def __init__(self, subject, object, checker):
        super(ConditionalRelation, self).__init__(subject, object)
        self.checker = checker

    def parse(self, *message, **context):
        if self.checker:
            length = result = None

            if callable(self.checker):
                result, length = self.checker(self, *message, **context)
            elif 'text' in context:
                length = len(self.checker) if context['text'].startswith(self.checker) else 0

                if length > 0:
                    result = self.checker

            if result:
                reply = {'move': length}
                if self.object:
                    reply['notify'] = {'to': self.object, 'data': {'condition': result}}

                return [reply, self.object]

        return 'error'


# Loop relation is a cycle that repeats object for specified or infinite number of times
class LoopRelation(Relation):
    def __init__(self, subject, object, n = None):
        super(LoopRelation, self).__init__(subject, object)
        self.n = n

    def parse(self, *message, **context):
        repeat = True
        error = restore = False

        reply = []

        if self.n and callable(self.n):
            context['from'] = self
            repeat = self.n(self, *message, **context)

        elif context['state']:
            if context.get('errors'):
                repeat = False

                if not self.n:
                    restore = True # Number of iterations is arbitrary if no restriction, we need to restore
                                   # last good context
                else:
                    error = True # Number is fixed so we have an error
            else:
                if self.n:
                    i = context['state']['n']

                    if i < self.n:
                        reply.append({'set_state': {'n': i + 1}})
                    else:
                        repeat = False # No more iterations

                else:
                    reply += ['forget_context', 'push_context'] # Prepare for the new iteration
                                                                # apply last changes and start new tracking
        else:
            # A very first iteration - init the variable and store the context
            reply += [{'set_state': {'n': 1 if self.n else True}}, 'push_context']

        if repeat:
            reply += [self.object, self] # We need to come back after object to think should we repeat or not
        else:
            if restore:
                reply.append('pop_context') # If we need to restore we need to repair context

            reply += ['forget_context', 'clear_state'] # No more repeats, clearing

            if error:
                reply.append('error')

        return reply


# Base process class, does parsing using list of event-condition-action items, moving from one abstract to another
class Process(Abstract):
    def __init__(self):
        super(Process, self).__init__()

        self.result = None

        self._queue = []
        self._callback = None

    def callback_event(self, info):
        if self.current != self._callback and self._callback: # We do not need infinite asking loops
            reply = self._callback.parse(info, **{'from': self, 'message': self.message, 'context' :self.context})

            if reply: # No need to store empty replies
                self._to_queue(False, current = self._callback, reply = reply)

                return True

        return False

    def _run_event_func(self, event):
        # We need to check should we pass self to event trigger or not, no need to do if for lambdas
        return event(self) if not hasattr(event, '__self__') else event()

    def run_event(self, event):
        can_run = self._run_event_func(event[1]) if event[1] else True
        result = None

        if can_run:
            # We need to check can we call event or not
            if not self.callback_event(event[0] + '_pre'):
                result = self._run_event_func(event[2])

                # Now we do a post-event call
                self.callback_event(event[0] + '_post')

        return can_run, result

    # Queue processing
    def _queueing_properties(self):
        return {'message': [], 'context': {}, 'current': None, 'reply': None}

    def _to_queue(self, update, **update_dict):
        top = dict([ (p, getattr(self, p)) for p in self._queueing_properties().keys()])
        top.update(update_dict)

        if not update:
            self._queue.append(top)
        else:
            self._queue[-1].update(top)

    def _queue_top_get(self, field, offset = -1):
        if self._queue and field in self._queue[offset]:
            return self._queue[offset].get(field)

        return self._queueing_properties().get(field)

    # Gets command string from reply or message
    def get_command(self, command, pull = False):
        data = None

        if isinstance(self.reply, dict) and command in self.reply:
            data = self.reply[command]

            if pull:
                del self.reply[command]

        elif command == self.reply:
            data = command

            if pull:
                self._to_queue(True, reply = None)

        elif command in self.message:
            data = command

            if pull:
                self.message.remove(command)

        elif self.message and isinstance(self.message[0], dict) and command in self.message[0]:
            data = self.message[0][command]

            if pull:
                del self.message[0][command]

        return data

    # Events
    def get_events(self):
        return [(
                    'new',
                    lambda self: self.get_command('new', True),
                    self.event_new
                ),
                (
                    'pull_message',
                    lambda self: not self.reply and self.message and
                                 isinstance(self.message[0], Abstract),
                    self.event_pull_message
                ),
                (
                    'stop',
                    lambda self: self.get_command('stop', True),
                    self.event_stop
                ),
                (
                    'skip',
                    lambda self: self.get_command('skip', True),
                    self.event_skip
                ),
                (
                    'queue_pop',
                    lambda self: not self.reply and len(self._queue) > 1,
                    self.event_pop
                ),
                (
                    'ok',
                    lambda self: not self.reply and len(self._queue) <= 1,
                    self.event_ok
                ),
                (
                    'next',
                    lambda self: isinstance(self.reply, Abstract),
                    self.event_next
                ),
                (
                    'queue_push',
                    lambda self: isinstance(self.reply, list) and len(self.reply) > 0,
                    self.event_push
                )]

    def event_start(self):
        return None

    def event_new(self):
        if len(self._queue) > 1:
            self._queue_top_get('context', -2).clear() # Old context should be gone

        del self._queue[:-1] # Removing previous elements from queue

    def event_pull_message(self):
        self._to_queue(True, current = self.message[0], reply = self.message[0])
        del self.message[0]

    def event_stop(self):
        return 'stop'    # Just stop at once where we are if callback does not care

    def event_skip(self):
        del self._queue[-2:] # Removing current and previous elements from queue

    def event_pop(self):
        self._queue.pop() # Let's move on

    def event_push(self):
        first = self.reply.pop(0) # First one is ready to be processed
        self._to_queue(False, reply = first)

    def event_ok(self):
        return 'ok' # We're done if nothing in the queue

    def event_next(self):
        self._to_queue(True, current = self.reply,
            reply = self.reply.parse(*self.message, **self.context))

    def event_unknown(self):
        return 'unknown'

    def event_result(self):
        return self.result

    def parse(self, *message, **context):
        if message or context:
            # If there is only a last fake item in queue we can just update it
            update = len(self._queue) == 1 and not self.message and not self.reply
            self._to_queue(update,
                           message = list(message) if message else self.message,
                           context = context or self.context,
                           current = None, reply = None)

        events = self.get_events()
        self.result = self.run_event(('start', None, self.event_start))[1]

        while True:
            event_found = False

            for event in events:
                result = self.run_event(event)
                if result[0]:
                    event_found = True

                    if result[1]:
                        self.result = result[1]
                        break

            # If we are here we've entered an uncharted territory
            if not event_found:
                self.result = self.run_event(('unknown', None, self.event_unknown))[1]

            # If there was a reply we need to ask callback before stopping
            if self.result and self.run_event(('result', None, self.event_result))[1]:
                break

        return self.result

    @property
    def callback(self):
        return self._callback

    @callback.setter
    def callback(self, value):
        if not value or (value and callable(value.parse)) and self._callback != value:
            self._callback = value

    @property
    def message(self):
        return self._queue_top_get('message')

    @property
    def context(self):
        return self._queue_top_get('context')

    @property
    def current(self):
        return self._queue_top_get('current')

    @property
    def reply(self):
        return self._queue_top_get('reply')


# Context process supports context modification commands
class SharedContextProcess(Process):
    def get_events(self):
        return super(SharedContextProcess, self).get_events() + \
            [(
                'add_context',
                lambda self: isinstance(self.get_command('add_context'), dict),
                self.event_add_context
            ),
            (
                'update_context',
                lambda self: isinstance(self.get_command('update_context'), dict),
                self.event_update_context
            ),
            (
                'delete_context',
                lambda self: self.get_command('delete_context'),
                self.event_delete_context
            )]

    def _context_add(self, key, value):
        self.context[key] = value

    def event_add_context(self):
        command = self.get_command('add_context', True)
        for k, v in command.items():
            if not k in self.context:
                self._context_add(k, v)

    def _context_set(self, key, value):
        self.context[key] = value

    def event_update_context(self):
        command = self.get_command('update_context', True)
        for k, v in command.items():
            self._context_set(k, v)

    def _context_delete(self, key):
        del self.context[key]

    def event_delete_context(self):
        command = self.get_command('delete_context', True)

        if isinstance(command, list):
            for k in command:
                if k in self.context:
                    self._context_delete(k)

        elif command in self.context:
            self._context_delete(command)


# Process that can save and restore context
# Useful for cases when process needs to try various routes in the graph
class StackingContextProcess(SharedContextProcess):
    def _queueing_properties(self):
        p = super(StackingContextProcess, self)._queueing_properties()
        p.update({'context_stack': []})

        return p

    def get_events(self):
        return super(StackingContextProcess, self).get_events() +\
           [(
                'push_context',
                lambda self: self.get_command('push_context', True),
                self.event_push_context
                ),
            (
                'pop_context',
                lambda self: self.get_command('pop_context', True) and self.is_tracking(),
                self.event_pop_context
                ),
            (
                'forget_context',
                lambda self: self.get_command('forget_context', True) and self.is_tracking(),
                self.event_forget_context
            )]

    def event_new(self):
        super(StackingContextProcess, self).event_new()

        if self.context_stack:
            self._to_queue(True, context_stack=self._queueing_properties()['context_stack']) # Clearing stack

    def is_tracking(self):
        return self.context_stack

    def _context_add(self, key, value):
        if not self.is_tracking():
            super(StackingContextProcess, self)._context_add(key, value)
        else:
            self.context_stack[-1].add(DictChangeOperation(self.context, DictChangeOperation.ADD, key, value))

    def _context_set(self, key, value):
        if not self.is_tracking():
            super(StackingContextProcess, self)._context_set(key, value)
        else:
            self.context_stack[-1].add(DictChangeOperation(self.context, DictChangeOperation.SET, key, value))

    def _context_delete(self, key):
        if not self.is_tracking():
            super(StackingContextProcess, self)._context_delete(key)
        else:
            self.context_stack[-1].add(DictChangeOperation(self.context, DictChangeOperation.DELETE, key))

    def event_push_context(self):
        self.context_stack.append(DictChangeGroup())

    def event_pop_context(self):
        self.context_stack[-1].undo()

    def event_forget_context(self):
        self.context_stack.pop()

    @property
    def context_stack(self):
        return self._queue_top_get('context_stack')


# Process with support of abstract states and notifications between them
class StatefulProcess(StackingContextProcess):
    def _queueing_properties(self):
        p = super(StatefulProcess, self)._queueing_properties()
        p.update({'states': {}})

        return p

    def get_events(self):
        return super(StatefulProcess, self).get_events() + \
        [(
            'set_state',
            lambda self: isinstance(self.get_command('set_state'), dict) and self.current,
            self.event_set_state
        ),
        (
            'clear_state',
            lambda self: self.get_command('clear_state', True) and self.current,
            self.event_clear_state
        ),
        (
            'notify',
            lambda self: isinstance(self.get_command('notify'), dict) and
                         isinstance(self.get_command('notify').get('to'), Abstract) and
                         'data' in self.get_command('notify'),
            self.event_notify
        )]

    def event_new(self):
        super(StatefulProcess, self).event_new()

        if self.states:
            self._to_queue(True,  states=self._queueing_properties()['states']) # Clearing states

    def event_next(self):
        # Self.reply is a new next, this is how the Process made
        self.context['state'] = self.states.get(self.reply) if self.reply in self.states else {}

        super(StatefulProcess, self).event_next()

        del self.context['state']

    def _set_state(self, abstract, state):
        if abstract in self.states:
            self.states[abstract].update(state)
        else:
            self.states[abstract] = state

    def event_set_state(self):
        self._set_state(self.current, self.get_command('set_state', True))

    def event_clear_state(self):
        if self.current in self.states:
            del self.states[self.current]

    def event_notify(self):
        data = self.get_command('notify', True)
        recipient = data['to']

        if not recipient in self.states:
            self._set_state(recipient, {})

        if not 'notifications' in self.states[recipient]:
            self.states[recipient]['notifications'] = {}

        self.states[recipient]['notifications'].update(data['data'])

    @property
    def states(self):
        return self._queue_top_get('states')


# Text parsing process supports error and move commands for text processing
class TextParsingProcess(StatefulProcess):
    def get_events(self):
        return super(TextParsingProcess, self).get_events() + \
        [(
            'error',
            lambda self: self.get_command('error'),
            self.event_error
         ),
         (
             'move',
             lambda self: self.get_command('move') and 'text' in self.context,
             self.event_move
         )]

    def event_start(self):
        super(TextParsingProcess, self).event_start()

        if not 'errors' in self.context: # Add errors if they are not in context
            self._context_add('errors', {})

        if not 'parsed_length' in self.context:
            self._context_add('parsed_length', 0)

    def event_new(self):
        super(TextParsingProcess, self).event_new()

        self._context_set('parsed_length', 0)

    def event_result(self):
        # If there are errors - result is always error
        if self.errors:
            self.result = 'error'

        return super(TextParsingProcess, self).event_result()

    def event_error(self):
        error = self.get_command('error', True)
        key = self.current or self

        if not self.is_tracking():
            self.errors[key] = error
        else:
            self.context_stack[-1].add(DictChangeOperation(self.errors, DictChangeOperation.SET, key, error))

    def event_move(self):
        move = self.get_command('move', True)

        self._context_set('text', self.context['text'][move:])
        self._context_set('parsed_length', self.parsed_length + move)

    @property
    def errors(self):
        return self.context['errors'] if 'errors' in self.context else {}

    @property
    def parsed_length(self):
        return self.context['parsed_length'] if 'parsed_length' in self.context else 0

