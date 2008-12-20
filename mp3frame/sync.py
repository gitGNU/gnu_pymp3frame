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

from __future__ import division, absolute_import
import struct
import array
from . import mp3bits, mp3ext, frames, side_info, errors


class BaseSync(object):
	"""BaseSync() -> object

Return an object that can store raw data from an MPEG audio file, identify
syncwords and tags within this data, and search for syncwords.
PhysicalFrameSync would normally be used instead."""
	
	def __init__(self):
		self.data = array.array('B')
		self.bytes_returned = 0
		
		# set to True when we see the EOF
		self.read_eof = False
		
		# the number of bytes in self.data that can be skipped when
		# looking for a syncword
		self.sync_skip = 0
		
		# The stream will be considered synchronized when
		#   (head & sync_mask) == sync_header,
		# where 'head' is the first 4 data bytes. Code may assume the high
		# 11 bits will always be set in both sync_* variables. The MP3 spec
		# suggests using the high 16 bits as a syncword once the expected
		# value is known (but note that it's probably a bad idea to base
		# sync_header on a VBR header frame).
		self.sync_header = 0xffe0 << 16
		self.sync_mask = self.sync_header
	
	done = property(lambda s: s.read_eof and not len(s.data),
			doc="True if all data from the input file has been processed.")
	
	def fromfile(self, file, bytes=4096):
		"""fromfile(file[, bytes]) -> None

Reads some data from the given file into the internal buffer."""
		
		if self.read_eof:
			raise errors.MP3UsageError('tried to write data after EOF')
		
		try:
			self.data.fromfile(file, bytes)
		except EOFError:
			# any data read before EOF will have been added
			self.read_eof = True
	
	def _is_sync(self, pos=0, sync_header=None, sync_mask=None):
		d = self.data
		head = ( (d[pos] << 24) | (d[pos+1] << 16)
				| (d[pos+2] << 8) | d[pos+3] )
		
		masked_head = (head & (sync_mask or self.sync_mask))
		return masked_head == (sync_header or self.sync_header)
		
	def resync(self, offset=0, header=None, mask=None):
		"""resync(offset=0[, header, mask]) -> int

Find the next syncword, ignoring the first 'offset' bytes in the buffer.
The ignored bytes remain in the buffer, but won't be checked for sync
patterns in the future (unless sync_skip is reset). If 'header' and 'mask'
are specified, they override sync_header and sync_mask.

Returns the sync position (as a buffer offset), or -1."""
		
		d = self.data
		offset = max(offset, self.sync_skip)
		while 1:
			dsub = d
			if offset > 0:
				dsub = d[offset:]
			
			try:
				pos = dsub.index(255) + offset
			except ValueError:
				self.sync_skip = len(d)
				return -1
			
			if pos + 4 > len(d):
				# too close to the end to check for sync
				self.sync_skip += pos
				return -1
			elif self._is_sync(pos, header, mask):
				self.sync_skip += pos
				return self.sync_skip
			
			self.sync_skip += pos + 1
			offset = self.sync_skip
	
	def identify(self):
		"""identify() -> None or tuple

Identify the data at the beginning of the internal buffer.
Return value:
   None - need more data
   ('sync',) - a syncword
   ('garbage', size) - unidentifiable data
   ('tag', size, type) - a comment tag
Note that the returned size may be greater than the amount of data
currently stored in the buffer."""
		
		d = self.data
		if len(d) < 4:
			if self.read_eof and d:
				return ('garbage', len(d))
			else:
				return None
		
		if self._is_sync():
			return ('sync',)
		
		(tagtype, tagsize) = mp3ext.identify_tag(d, self.read_eof)
		if tagsize > 0:
			return ('tag', tagsize, tagtype)
		elif tagsize == -1:
			# need more data to determine whether this is a tag
			return None
		
		# this data looks like garbage; try to find the next syncword
		# (we know there are at least 4 bytes in the buffer)
		syncpos = self.resync()
		if syncpos > 0:
			return ('garbage', syncpos)
		
		# we can't sync, but not all the data is necessarily garbage;
		# there could be a partial sync pattern at the end
		if self.sync_skip > 0:
			return ('garbage', self.sync_skip)
		else:
			return None
	
	def advance(self, bytes):
		"""advance(bytes) -> None

Discards the specified number of bytes from the front of the buffer."""
		
		if (bytes > len(self.data)) or (bytes < 0):
			raise errors.MP3UsageError("invalid byte count")
		
		self.bytes_returned += bytes
		self.data = self.data[bytes:]
		self.sync_skip = max(0, self.sync_skip - bytes)



class PhysicalFrameSync(BaseSync):
	"""PhysicalFrameSync() -> object

Return an object that will interpret the various types of data found in an
MPEG audio file and construct objects for examining them."""
	
	def __init__(self):
		BaseSync.__init__(self)
		self.synced = True
		self.frames_returned = 0
		
		# base_framesize is the size of a non-padded freeform frame; if set,
		# we'll assume all frames are this size. A value of -1 (the default)
		# means this will be autodetected; a value of 0 will disable this
		# behaviour (and force frame sizes to be calculated by searching for
		# the next syncword).
		self.base_framesize = -1
	
	def readitem(self):
		"""readitem() -> None or 2-tuple

Remove the next item from the interal buffer and return it.
Return value:
   None - need more data
   ('frame', MP3Frame)
   ('tag', CommentTag)
   ('garbage', array) - unidentifiable bytes"""
		
		d = self.data
		if len(d) < 4:
			return None
		
		ident = self.identify()
		if not ident:
			return None
		
		dtype = ident[0]
		if dtype != 'sync':
			self.synced = (dtype != 'garbage')
			
			size = ident[1]
			if len(d) < size:
				return None
			
			data = d[:size]
			self.advance(size)
			
			if dtype == 'tag':
				tagtype = ident[2]
				return (dtype, frames.CommentTag(tagtype, data))
			else:
				return (dtype, data)
		
		fr = self._create_frame()
		if type(fr) == str:
			# we got an error code instead of a frame
			if fr == 'moredata':
				if not self.read_eof:
					return None
				
				# treat all remaining data as garbage
				size = len(d)
			else:
				assert fr == 'resync'
				size = 1
			
			self.synced = False
			ret = d[:size]
			self.advance(size)
			return ('garbage', ret)
		else:
			return ('frame', fr)
	
	# Assume there's a frame at the start of self.data, and return it.
	# Returns an MP3Frame instance, 'resync', or 'moredata'
	def _create_frame(self):
		d = self.data
		# we have a frame header; try to determine the frame size
		
		head = frames.FrameHeader(d)
		
		headsz = 4
		if head.protection_bit == 0:
			headsz += 2
		
		try:
			sz = head.frame_size
			if head.layer_index == 1:  # layer 3
				sidesz = head.side_info_size
			else:
				sidesz = 0
			
			if len(d) < (sz or (headsz + sidesz)):
				return 'moredata'
		except errors.MP3DataError:
			# on closer inspection, this isn't a valid frame
			return 'resync'
		
		# we have the side info, if applicable;
		# as well as the full frame if its size is known
		
		if sidesz:
			raw_si = d[headsz:headsz+sidesz]
			si_obj = side_info.SideInfo(head.version_index,
					head.channel_mode, raw_si)
		else:
			raw_si = None
			si_obj = None
		
		if not sz and self.base_framesize:
			# this is a free-format frame; all such frames need to be the
			# same size within a file (except for padding), and we have an
			# expected size
			sz = self.base_framesize
			if head.padding:
				sz += head.sample_size
		
		if not sz:
			# this is a free-format frame; we don't know the expected size,
			# so we'll try to find the next syncword (and won't consider
			# this a resync)
			
			offset = headsz + sidesz
			if si_obj:
				# the frame can't end before part2_3_end,
				# so skip all data until that point
				offset += max(0, si_obj.part2_3_end)
			
			# search for another syncword with the same MPEG version, layer,
			# protection_bit, bitrate (free format), and samplerate
			sync_header = (0xff << 24) | (d[1] << 16) | (d[2] << 8)
			sz = self.resync(offset, sync_header, 0xfffffc00)
			if sz == -1:
				if len(d) >= 8192:
					# we should have enough data to locate another syncword;
					# assume this 'free-format frame' was just garbage
					self.sync_skip = 0
					return 'resync'
				elif not self.read_eof:
					return 'moredata'
				
				# we won't be getting more data, so return everything
				# until EOF -- excluding the id3v1 tag, if present
				sz = len(d)
				if sz > 128:
					tagsz = mp3ext.id3v1_size(d[-128:], True)
					if tagsz > 0:
						sz -= tagsz
			
			# found a syncword; now that the frame size is known,
			# store it for future use
			assert sz >= offset
			if self.base_framesize < 0:
				base_sz = sz
				if head.padding:
					base_sz -= head.sample_size
				self.base_framesize = base_sz
		
		assert sz > 0
		if len(d) < sz:
			return 'moredata'
		
		# we have the full frame
		
		fr = frames.MP3Frame()
		fr.header = head
		if si_obj:
			fr.side_info = si_obj
		fr.raw_body = d[headsz+sidesz:sz]
		
		if head.protection_bit == 0:
			fr.crc16 = (d[4] << 8) | d[5]
		else:
			fr.crc16 = None
		
		fr.resynced = not self.synced
		fr.frame_number = self.frames_returned
		fr.byte_position = self.bytes_returned  # managed by BaseSync
		
		self.advance(sz)
		self.frames_returned += 1
		self.synced = True
		return fr



class FileSyncWrapper(object):
	"""FileSyncWrapper(sync, file) -> object

Return a wrapper that can be used to conveniently access a PhysicalFrameSync
or LogicalFrameSync instance; data will be automatically fed into this object
from the specified file as required."""

	def __init__(self, sync, file):
		self.file = file
		self.sync = sync
		self.max_buffer = 4*1024*1024
	
	
	def readitem(self):
		"""readitem()

Call sync.readitem() and return the result if it's not None.
Otherwise, feed the sync some data from the file and retry.
Returns None only at the end of the file."""

		while not self.sync.done:
			rv = self.sync.readitem()
			if rv is None:
				if len(self.sync.data) >= self.max_buffer:
					raise errors.MP3ImplementationLimit(
							'sync buffer reached maximum size')
				
				self.sync.fromfile(self.file)
			else:
				return rv
		
		return None
	
	
	def readframe(self):
		"""readframe()

Like readitem, but skips anything that's not a frame."""
		while 1:
			rv = self.readitem()
			if not rv:
				return None
			elif rv[0] == 'frame':
				return rv[1]
	
	
	def items(self):
		"""items() -> generator

Return a generator that repeatedly calls readitem.  This can be used as:
  for (itemtype, item) in fsWrapper.items(): ..."""
		while 1:
			x = self.readitem()
			if x is None: break
			yield x
	
	
	def frames(self):
		"""frames() -> generator

Return a generator that repeatedly calls readframe.  This can be used as:
  for frame in fsWrapper.frames(): ..."""
		while 1:
			x = self.readframe()
			if x is None: break
			yield x




class LogicalFrameAssembler(object):
	__slots__ = ('reservoir', 'last_end', 'ancillary_skipped')
	
	def __init__(self):
		self.reservoir = array.array('B')
		self.last_end = 0
	
	def frame_in(self, fr):
		"""frame_in(MP3Frame) -> byte array or None

Update the bit reservoir based on the given frame, and return a byte array
containing the frame's data.  Returns None if the frame references any data
that's not available."""
		
		raw_body = fr.raw_body
		unused_reservoir = len(self.reservoir) - self.last_end
		if fr.header.layer_index != 1:
			# layer 1/2 frames don't use a bit reservoir
			self.ancillary_skipped = unused_reservoir
			if unused_reservoir:
				self.reservoir = self.reservoir[:0]
				self.last_end = 0
			
			return raw_body
		
		begin = fr.side_info.main_data_begin
		self.ancillary_skipped = unused_reservoir - begin
		
		main_len = fr.side_info.part2_3_bytes
		if begin > len(self.reservoir):
			data = None  # invalid main_data_begin
		else:
			end = main_len - begin
			if end > len(raw_body):
				print '!! end=%d   mainlen=%d begin=%d  rblen=%d'%(
						end,main_len, begin,len(raw_body))
				data = None  # invalid length
			elif end < 0:
				assert begin > 0
				data = self.reservoir[-begin:end]
			elif begin > 0:
				data = self.reservoir[-begin:]
				data += raw_body[:end]
			else:
				data = raw_body[:end]
		
		# store the data; we need to keep at least 511 bytes in the reservoir
		if (len(raw_body) >= 511) or not self.reservoir:
			self.reservoir = raw_body[:]
		else:
			if (len(self.reservoir) + len(raw_body)) > 4096:
				keep = max(1, 511 - len(raw_body))
				self.reservoir = self.reservoir[-keep:]
			self.reservoir += raw_body
		
		if data is None:
			self.last_end -= len(raw_body)
		else:
			assert len(data) == main_len
			
			unused_bytes = len(data) - end
			self.last_end = len(raw_body) - unused_bytes
		
		return data


class LogicalFrameSync(PhysicalFrameSync):
	__slots__ = ('assembler')
	
	def __init__(self):
		PhysicalFrameSync.__init__(self)
		self.assembler = LogicalFrameAssembler()
	
	def readitem(self):
		rv = PhysicalFrameSync.readitem(self)
		if rv and rv[0] == 'frame':
			fr = rv[1]
			fr.logical_body = self.assembler.frame_in(fr)
			fr.ancillary_skipped = self.assembler.ancillary_skipped
			return ('frame', fr)
		else:
			return rv
