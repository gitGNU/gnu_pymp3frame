class MP3DataError(Exception): pass
class MP3ReservedError(MP3DataError): pass

class MP3UsageError(Exception): pass

class MP3ImplementationLimit(Exception): pass
