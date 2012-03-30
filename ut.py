# Universal Translator base classes
# (c) krvss 2011-2012

import types

# Base class for all communicable objects
class Abstract(object):
    def __init__(self):
        self._callbacks = []

    def parse(self, message, context = None):
        return None

    def call(self, callback, forget = False):
        if forget and callback in self._callbacks:
            self._callbacks.remove(callback)
        else:
            if callback and callable(callback.parse):
                self._callbacks.append(callback)

    def _notify(self, message, context = None):
        for callee in self._callbacks:
            if callable(callee.parse):
                callee.parse(message, context)


# Notion is an abstract with name
class Notion(Abstract):
    def __init__(self, name):
        super(Abstract, self).__init__()
        self.name = name

    def parse(self, message, context = None):
        return None

    def __str__(self):
        if self.name:
            return "'%s'" % self.name


# Relation is a connection between 1 or more abstracts
class Relation(Abstract):
    def __init__(self, subject, object):
        super(Relation, self).__init__()
        self._subject = None
        self._object = None

        self.subject = subject
        self.object = object

    def _disconnect(self, value, target):
        if value:
            self._notify("unrelating", {"relation": self, target: value})
            self.call(value, True)

    def _connect(self, value, target):
        if value:
            self.call(value)
            self._notify("relating", {"relation": self, target: value})

    @property
    def subject(self):
        return self._subject

    @subject.setter
    def subject(self, value):
        if value == self.subject:
            return

        self._disconnect(self.subject, "subject")
        self._subject = value
        self._connect(value, "subject")

    @property
    def object(self):
        return self._object

    @object.setter
    def object(self, value):
        if value == self.object:
            return

        self._disconnect(self.object, "object")
        self._object = value
        self._connect(value,  "object")

    def __str__(self):
        return "<%s - %s>" % (self.subject, self.object)


# Function notion is notion that can call custom function
class FunctionNotion(Notion):
    def __init__(self, name, function):
        super(FunctionNotion, self).__init__(name)
        self.function = function if callable(function) else None

    def parse(self, message, context = None):
        return self.function(self, context) if self.function else None


# Complex notion is a notion that relates with other notions (objects)
class ComplexNotion(Notion):
    def __init__(self, name, relation = None):
        super(ComplexNotion, self).__init__(name)
        self._relations = []

        self._relate(relation)

    def _relate(self, relation):
        if relation and (relation not in self._relations):
            self._relations.append(relation)

            if relation.subject != self:
                relation.subject = self

    def _unrelate(self, relation):
        if relation and (relation in self._relations):
            self._relations.remove(relation)

            if relation.subject == self:
                relation.subject = None

    def parse(self, message, context = None):
        reply = super(ComplexNotion, self).parse(message)

        if not reply:
            if message == "relating":
                if context.get("subject") == self:
                    self._relate(context["relation"])

            elif message == "unrelating":
                if context.get("subject") == self:
                    self._unrelate(context["relation"])

            else: # Returning relations by default
                if self._relations:
                    return self._relations[0] if len(self._relations) == 1 else list(self._relations)


# Selective notion: complex notion that can consist of one of its objects
class SelectiveNotion(ComplexNotion):
    def __init__(self, name, relation = None):
        super(SelectiveNotion, self).__init__(name, relation)

    def parse(self, message, context = None):
        if context:
            if self in context:
                if "error" in context:
                    cases = context[self]

                    if cases:
                        case = cases.pop(0)

                        return ["restore", {"update": {self: cases}}, "store", case, self]
                    else:
                        return ["clear", "error"]

                else:
                    return "clear"

        reply = super(SelectiveNotion, self).parse(message, context)

        if not reply or (reply and not type(reply) is types.ListType):
            return reply

        elif context:
            case = reply.pop(0)
            context[self] = reply

            return ["store", case, self]

        return reply


# Next relation is just a simple sequence relation
class NextRelation(Relation):
    def __init__(self, subject, object):
        super(NextRelation, self).__init__(subject, object)

    def parse(self, message, context = None):
        return self.object


# Conditional relation is a condition to go further if message starts with sequence
class ConditionalRelation(Relation):
    def __init__(self, subject, object, checker):
        super(ConditionalRelation, self).__init__(subject, object)
        self.checker = checker

    def parse(self, message, context = None):
        if self.checker:
            result = None

            if callable(self.checker):
                result, length = self.checker(message)
            else:
                length = len(self.checker) if message.startswith(self.checker) else 0

                if length > 0:
                    result = self.checker

            if result:
                if context and self.object: # May be this is something for the object
                    context[self.object] = result

                return [{"move": length}, self.object]

        return "error"


# Loop relation is a cycle that repeats object for specified or infinite number of times
class LoopRelation(Relation):
    def __init__(self, subject, object, n = None):
        super(LoopRelation, self).__init__(subject, object)
        self.n = n

    def parse(self, message, context = None):
        repeat = True
        error = restore = False

        if self.n and callable(self.n):
            repeat = self.n(self, context)

        elif context:
            if self in context:
                if "error" in context:
                    repeat = False

                    if not self.n:
                        restore = True # Number of iterations is arbitrary if no restriction, we need to restore last good context
                    else:
                        error = True # Number is fixed so we have an error
                else:
                    if self.n:
                        i = context[self]

                        if i < self.n:
                            context[self] = i + 1
                        else:
                            repeat = False # No more iterations

            else:
                context[self] = 1 if self.n else True # Initializing the loop

        if repeat:
            reply = ["store", self.object, self] # Self is a new next to think should we repeat or not
        else:
            if restore:
                reply = ["restore", "clear"] # Clean up after restore needed to remove self from context
            else:
                reply = ["clear"] # No need to restore, just clear self

            if error:
                reply.append("error")

        return reply


# Base process class
class Process(Abstract):

    def get_next(self, abstract, message, context):
        raise NotImplementedError()

    def parse(self, message, context = None):
        if not context:
            context = {}
            abstract = None
        else:
            abstract = context.get("start") #TODO we can use message for start

        initial_length = len(message)
        stop = False

        while not stop: #TODO refactor
            next = self.get_next(abstract, message, context)

            if "message" in next:
                message = next["message"]

            if "abstract" in next:
                abstract = next["abstract"]

            if "stop" in next:
                stop = next["stop"]

        return {"result": not "error" in context, "length": initial_length - len(message)}


# Parser process
class ParserProcess(Process):
    def __init__(self):
        super(ParserProcess, self).__init__()

    def _get_context_info(self, context, name, default):
        if not self in context:
            context[self] = {}

        if not name in context[self]:
            context[self][name] = default
            return default
        else:
            return context[self][name]

    def _get_stack(self, context):
        return self._get_context_info(context, "stack", [])

    def _get_states(self, context):
        return self._get_context_info(context, "states", {})

    def _get_error(self, context):
        if not "error" in context:
            error = []
            context["error"] = error
        else:
            error = context["error"]

        return error

    def _progress_notify(self, info, abstract, parsing_message = None, parsing_context = None):
        self._notify(info, {"abstract": abstract,
                            "message": parsing_message or "",
                            "context": parsing_context or ""})

    def _rollback(self, context):
        abstract = None
        reply = None

        if self._can_rollback(context):
            abstract, reply = self._get_stack(context).pop(0)

            self._progress_notify("rolled_back", abstract)

        return abstract, reply

    def _can_rollback(self, context):
        return len(self._get_stack(context)) > 0

    def _add_to_stack(self, context, abstract, reply):
        stack = self._get_stack(context)
        stack.insert(0, (abstract, reply))

        self._progress_notify("added_to_stack", abstract)

    def get_next(self, abstract, message, context):
        # Check do we have where to go to
        if not abstract or not isinstance(abstract, Abstract): # TODO: What if abstract is string with command - keep current in context?
            self._progress_notify("not_abstract", abstract)

            if self._can_rollback(context):
                abstract, reply = self._rollback(context)
            else:
                return {"stop": True} # Stopping

        # Asking!
        else:
            self._progress_notify("abstract_current", abstract, message, context)

            reply = abstract.parse(message, context)

        # Got sequence?
        if type(reply) is types.ListType:
            if len(reply) >= 1:
                r = reply.pop(0) # First one is ready to be processed

                if reply: # No need to push empty list
                    self._add_to_stack(context, abstract, reply)

                reply = r
            else:
                return {"abstract": None} # Let's try to roll back

        # Got command?
        if isinstance(reply, str):
            reply = {reply: None}

        if isinstance(reply, dict):
            for name, arg in reply.iteritems():
                # Commands processing
                if name == "restore":
                    message, old_context = self._get_states(context)[abstract]

                    context.clear() # Keeping context object intact
                    context.update(old_context)

                    if abstract in self._get_states(context):
                        del self._get_states(context)[abstract]

                    self._progress_notify("restored_for", abstract, message)

                elif name == "update":
                    context.update(arg)

                    self._progress_notify("updated_for", abstract, message)

                elif name == "store":
                    self._get_states(context)[abstract] = (message, dict(context))

                    self._progress_notify("storing", abstract, message)

                elif name == "clear":
                    if abstract in self._get_states(context): # TODO: copy of restore part, combine or remove
                        del self._get_states(context)[abstract]

                    if arg != "state":
                        if abstract in context:
                            del context[abstract]

                elif name == "error":
                    error = arg or abstract

                    self._get_error(context).append(error)

                    self._progress_notify("error_at", error)

                elif name == "move":
                    message = message[arg:]

                elif name == "replace":
                    message = arg

            abstract = None

        else:
            abstract = reply

        return {"abstract": abstract, "message": message}
