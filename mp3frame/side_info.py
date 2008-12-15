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
from . import mp3bits, bitfields
import array
import weakref


### Channel structures

class ChannelBase(object):
	__slots__ = ('_side_info', 'granules')
	def __init__(self, side_info, granules):
		self._side_info = side_info
		self.granules = granules
	
	_raw_side_info = property(lambda s: s._side_info.raw_data)

class MPEG1Channel(ChannelBase):  # abstract class (doesn't provide _scfsi)
	__slots__ = ()
	
	def _get_scfsi(self):
		num = self._scfsi
		return tuple([ (num & m)//m for m in (8,4,2,1) ])
	
	def _set_scfsi(self, val):
		val = tuple(val)
		if len(val) != 4:
			raise ValueError('scfsi tuple must have length 4')
		
		num = 0
		for i in range(4):
			if val[i]:
				num |= (8 >> i)
		self._scfsi = num
	
	scfsi = property(_get_scfsi, _set_scfsi)

class MPEG1MonoChannel(MPEG1Channel):
	__slots__ = ()
	_scfsi = bitfields.make_property('_raw_side_info', 14, 4)

class MPEG1StereoChannel_C0(MPEG1Channel):
	__slots__ = ()
	_scfsi = bitfields.make_property('_raw_side_info', 12, 4)

class MPEG1StereoChannel_C1(MPEG1Channel):
	__slots__ = ()
	_scfsi = bitfields.make_property('_raw_side_info', 16, 4)


### Granule structures
# A different granule class is created (via _make_gran_class) for every
# possible offset within the side info; the fields are also slightly
# different between MPEG1 and MPEG2/2.5.

class GranuleBase(object):
	__slots__ = ('_side_info',)
	
	def __init__(self, side_info):
		self._side_info = side_info
	
	_raw_side_info = property(lambda s: s._side_info.raw_data)


def _make_bdprop(flag0=None, flag1=None):
	# Returns a property that acts like one of the given properties,
	# depending on the value of blocksplit_flag when it's accessed;
	# MP3UsageError is raised if no property was specified for that state.
	
	props = (flag0, flag1)
	
	def get_blockdata_field(gran):
		p = props[gran.blocksplit_flag]
		if p: return p.fget(gran)
		else: err(gran)
	
	def set_blockdata_field(gran, val):
		p = props[gran.blocksplit_flag]
		if p: p.fset(gran, val)
		else: err(gran)
	
	def err(gran):
		state = "set" if gran.blocksplit_flag else "cleared"
		raise mp3bits.MP3UsageError( "field not present"
				" when blocksplit_flag " + state )
	
	return property(get_blockdata_field, set_blockdata_field)


def _add_blockdata_fields(offset, cls):
	def bf(pos, bits):
		return bitfields.make_property('_raw_side_info', offset + pos, bits)
	
	def arr(pos, bits, count):
		prop = bf(pos, count * bits)
		(fget, fset) = (prop.fget, prop.fset)
		
		mask = (1 << bits) - 1
		shifts = range(bits*(count-1), -1, -bits)
		
		def get_tuple(gran):
			val = fget(gran)
			return tuple([ ((val >> sh) & mask) for sh in shifts ])
		
		def set_tuple(gran, val):
			if len(val) != count:
				raise ValueError('value must have length %d' % count)
			
			num = 0
			for x in val:
				num = (num << bits) | (x & mask)
			fset(gran, num)
		
		return property(get_tuple, set_tuple)
	
	# fields (with sizes) when blocksplit_flag cleared:
	#   table_select, 15
	#   region_address1, 4
	#   region_address2, 3
	# when blocksplit_flag set:
	#   block_type, 2
	#   switch_point, 1
	#   table_select, 10
	#   subblock_gain, 9
	
	cls.table_select = _make_bdprop(flag0=arr(0, 5, 3), flag1=arr(3, 5, 2))
	cls.region_address1 = _make_bdprop(flag0=bf(15, 4))
	cls.region_address2 = _make_bdprop(flag0=bf(19, 3))
	cls.block_type = _make_bdprop(flag1=bf(0, 2))
	cls.switch_point = _make_bdprop(flag1=bf(2, 1))
	cls.subblock_gain = _make_bdprop(flag1=arr(13, 3, 3))
	
	return 22


def _make_gran_class(lsf, offset, classname):
	d = { '__slots__': () }
	cls = type(classname, (GranuleBase,), d)
	
	fields = (
		('part2_3_length', 12),
		('big_values', 9),
		('global_gain', 8),
		('scalefac_compress', 9 if lsf else 4),
		('blocksplit_flag', 1),
		(_add_blockdata_fields,),
		None if lsf else ('preflag', 1),
		('scalefac_scale', 1),
		('count1table_select', 1)
	)
	
	for item in fields:
		if not item:
			pass
		elif callable(item[0]):
			offset += item[0](offset, cls, *item[1:])
		else:
			(name, bits) = item
			setattr(cls, name, bitfields.make_property(
					'_raw_side_info', offset, bits))
			offset += bits
	
	return cls


### SideInfo classes

def _calc_part2_3_bytes(side_info):
	total = 0
	for chan in side_info.channels:
		for gran in chan.granules:
			total += gran.part2_3_length
	return (total + 7) // 8

class SideInfoBase(object):
	__slots__ = ()
	
	part2_3_bytes = property(_calc_part2_3_bytes)
	part2_3_end = property(
			lambda s: s.part2_3_bytes - s.main_data_begin )


def _make_si_class(lsf, mono):
	mpver = 'MPEG' + ('2' if lsf else '1')
	clsprefix = mpver + ('Mono' if mono else 'Stereo')
	
	# these are just used for table lookups
	# (the values for non-lsf and stereo modes are arbitrary)
	version_index = (2 if lsf else 3)
	channel_mode = (3 if mono else 0)
	
	grancount = (1 if lsf else 2)
	chancount = (1 if mono else 2)
	
	### build the granules classes
	
	if lsf:
		chclasses = (ChannelBase, ChannelBase)
	else:
		if mono:
			chclasses = (MPEG1MonoChannel,)
		else:
			chclasses = (MPEG1StereoChannel_C0, MPEG1StereoChannel_C1)
	
	offsets = mp3bits.side_info_bit_offsets(version_index, channel_mode)
	grclasses = [[], []]
	i = 0
	for g in range(grancount):
		for c in range(chancount):
			name = clsprefix + 'Granule_'
			if grancount > 1: name += 'G%d' % g
			if chancount > 1: name += 'C%d' % c
			
			grclasses[c].append( _make_gran_class( lsf,
					offsets[i], name.strip('_') ))
			i += 1
	assert i == len(offsets)
	
	### build the main SideInfo class
	
	si_size = mp3bits.side_info_size(version_index, channel_mode)
	blank_si = array.array('B', '\0'*si_size)
	
	def init_side_info(self, raw_data=None):
		selfref = weakref.proxy(self)
		chanlist = []
		for c in range(chancount):
			grans = tuple([ grclasses[c][g](selfref)
					for g in range(grancount) ])
			chanlist.append( chclasses[c](selfref, grans) )
		
		self.channels = tuple(chanlist)
		if raw_data:
			self.raw_data = raw_data
		else:
			self.raw_data = blank_si[:]
	
	clsname = clsprefix + 'SideInfo'
	si_cls = SideInfoBase.__class__(clsname, (SideInfoBase,), {
		'__slots__': ('channels', 'raw_data', '__weakref__'),
		'__init__': init_side_info,
	})
	
	si_cls.main_data_begin = bitfields.make_property(
			'raw_data', 0, 8 if lsf else 9)
	if lsf:
		si_cls.private_bits = bitfields.make_property(
				'raw_data', 8, 1 if mono else 2)
	else:
		si_cls.private_bits = bitfields.make_property(
				'raw_data', 9, 5 if mono else 3)
	
	return si_cls

_si_classes = ( (_make_si_class(0,0), _make_si_class(0,1)),
		(_make_si_class(1,0), _make_si_class(1,1)) )


def SideInfo(version_index, channel_mode, raw_data=None):
	"""SideInfo(version_index, channel_mode, raw_data) -> object

Return an object representing MPEG layer 3 side info, based on the given
parameters. The class of the object varies based on the MPEG version and
channel mode (only applicable fields are present, and field sizes vary)."""
	
	lsf = (version_index != 3)
	mono = (channel_mode == 3)
	return _si_classes[lsf][mono](raw_data)
