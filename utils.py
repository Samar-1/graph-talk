# Class to track dict changes: add, change and delete key
# Operations of the same type are not stacked, latter one replaces earlier of the same type
class DictChangeOperation(object):
    Operations = ('add', 'set', 'delete')
    ADD, SET, DELETE = Operations

    def __init__(self, dict, type, key, value = None):

        if type not in self.Operations:
            raise ValueError(type)

        self._dict, self._type, self._key = dict, type, key
        self._value, self._old_value = value, None

    def do(self):
        if self._type == self.SET and not self._key in self._dict:
            self._type = self.ADD # No old value, so it is rather add

        if self._type == self.ADD:
            self._dict[self._key] = self._value

        elif self._type == self.SET:
            self._old_value = self._dict[self._key]
            self._dict[self._key] = self._value

        else:
            self._old_value = self._dict[self._key]
            del self._dict[self._key]

    def undo(self):
        if self._type == self.ADD:
            del self._dict[self._key]
        else:
            self._dict[self._key] = self._old_value

    def merge(self, other):
        if other._dict == self._dict and other._type == self._type == self.SET and other._key == self._key:
            self._value = other._value
            return True

        return False

    def __str__(self):
        s = '%s %s' % (self._type, self._key)
        if self._type == self.ADD or self._type == self.SET:
            s += '=%s' % self._value

        if self._type == self.SET:
            s += '<-%s' %self._old_value

        return s

    def __repr__(self):
        return self.__str__()


# Stack of dictionary changes for keeping of changes and mass operations
class DictChangeGroup(object):
    def __init__(self):
        self._stack = []

    def add(self, change, do = True):
        if not self._stack or not self._stack[-1].merge(change):
            self._stack.append(change)

        if do:
            change.do()

    def do(self):
        for c in self._stack:
            c.do()

    def undo(self):
        for c in self._stack.__reversed__():
            c.undo()



