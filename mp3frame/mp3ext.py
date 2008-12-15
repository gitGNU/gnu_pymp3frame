# Copyright (c) 2008 Michael Gold
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
# CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
# TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""\
Constants and utility functions for dealing with non-standard data fields
like comment tags that appear in MPEG audio files.  Like mp3bits, the
functions in this module work with raw data."""


def identify_tag(data, eof):
	"""Identify the comment tag at the beginning of the byte array.
Returns (type, size), where type is 'id3v1', 'id3v2', 'apev2', 'lyrics3v1',
or 'lyrics3v2'; or None if it can't be identified.

If type is None, size is 0 if this isn't a tag or -1 it more data is needed
(-1 won't be returned if eof is True).  Otherwise it's the tag size in bytes.\
"""
	v2 = id3v2_size(data)
	if v2 > 0: return ('id3v2', v2)
	
	v1 = id3v1_size(data, eof)
	if v1 > 0: return ('id3v1', v1)
	
	ape = apev2_size(data)
	if ape > 0: return ('apev2', ape)
	
	lyr2 = lyrics3v2_size(data)
	if lyr2 > 0: return ('lyrics3v2', lyr2)
	
	lyr1 = lyrics3v1_size(data, eof)
	if lyr1 > 0: return ('lyrics3v1', lyr1)
	
	if eof:
		return (None, 0)
	else:
		# return -1 if any were -1
		return (None, v2 or v1 or ape or lyr2 or lyr1)


### functions for detecting specific tag types

def _startswith(arr, prefix, arr_offset=0):
	i = 0
	while i < len(prefix):
		if arr[i + arr_offset] != prefix[i]:
			return False
		i += 1
	return True

def _enc(text): return tuple([ ord(x) for x in text ])
_ID3 = _enc('ID3')
_TAG = _enc('TAG')
_APETAGEX = _enc('APETAGEX')
_LYRICSBEGIN = _enc('LYRICSBEGIN')
_LYRICSEND = _enc('LYRICSEND')
_LYRICS200 = _enc('LYRICS200')


def id3v2_size(data, eof=0):
	if len(data) >= 3 and not _startswith(data, _ID3):
		return 0   # not an ID3 tag
	elif len(data) < 10:
		# can't determine size or tell whether this is an ID3 tag
		return -1
	
	if (data[3] == 0xff) or (data[4] == 0xff):
		return 0
	for i in data[6:10]:
		if i >= 0x80: return 0
	
	# this is an ID3v2 tag
	flags = data[5]
	id3len = 10  # header size
	id3len += (data[6] << 21) + (data[7] << 14) + (data[8] << 7) + data[9]
	if flags & 0x40:
		id3len += 10  # an extended header is present
	
	return id3len

def id3v1_size(data, eof, offset=0):
	taglen = len(data) - offset
	if taglen >= 3 and not _startswith(data, _TAG, offset):
		return 0
	
	if taglen == 128 and eof:
		return 128
	elif taglen < 128 and not eof:
		return -1
	
	return 0

def apev2_size(data, eof=0):
	if len(data) >= 8 and not _startswith(data, _APETAGEX):
		return 0
	elif len(data) < 16:
		return -1
	
	apelen = 32  # header size
	apelen += struct.unpack('<I', data[12:16])[0]
	return apelen

def lyrics_field_info(data, offset=0):
	"""lyrics_field_info(data, offset=0) -> None or (str, size) or (None, size)

Return information about a single field in a lyrics tag.
There must be at least 8 bytes of data available.
Returns None if this isn't a valid field; otherwise, return (name, size):
   name - a 3-character string; or None if this is the tag length field
   size - the size associated with this field"""
	
	def _ucase(pos): return data[pos] > 64 and data[pos] <= 64+26
	def _val(pos, len):
		ret = 0
		for i in range(pos, pos+len):
			ch = data[i]
			if ch < 48 or ch > 57: return None  # not a digit
			ret = (ret * 10) + (ch - 48)
		return ret
	
	if _ucase(offset) and _ucase(offset+1) and _ucase(offset+2):
		v = _val(offset+3, 5)
		if v is None:
			return None
		else:
			return ( data[offset:offset+3].tostring(), v )
	
	v = _val(offset, 6)
	if v is None:
		return None       # not a lyrics field
	else:
		return (None, v)  # end indicator

def lyrics3v2_size(data, eof=0):
	if len(data) >= 11 and not _startswith(data, _LYRICSBEGIN):
		return 0
	
	pos = 11
	while pos+8 < len(data):
		if pos >= 0x80000:
			return 0  # sanity check: not a valid tag
		
		f = lyrics_field_info(data, pos)
		if f is None:
			return 0  # not a lyrics field
		
		(name, size) = f
		if name is None:  # end of tag
			if pos != size:
				return 0  # invalid length
			
			pos += 6
			break
		else:
			pos += size + 8
	
	if pos+9 > len(data):
		return -1
	elif _startswith(data, _LYRICS200, pos):
		return pos + 9
	else:
		return 0

def lyrics3v1_size(data, eof):
	# maximum length: 5100 bytes of lyrics + 20 bytes for header and footer
	taglen = len(data)
	if taglen >= 11 and not _startswith(data, _LYRICSBEGIN):
		return 0
	
	# found a start tag; the end tag is located 9 or 137 bytes from EOF
	if taglen > 5120+128:
		# tag is longer than the maximum size
		# (+ 128 bytes to allow for an ID3v1 tag)
		return 0
	elif not eof:
		# can't locate the end tag yet
		return -1
	elif taglen < 20:
		# no room for header and footer
		return 0
	elif taglen >= 128+20 and id3v1_size(data, eof, len(data) - 128) == 128:
		# an ID3v1 tag is present and needs to be ignored
		taglen -= 128
	
	if _startswith(data, _LYRICSEND, taglen - 9):
		return taglen
	else:
		return 0
