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

_high0_mask = tuple([ (0xff >> x) for x in range(9) ])
_high1_mask = tuple([ ((0xff00 >> x) & 0xff) for x in range(9) ])
_low0_mask = tuple(reversed(_high1_mask))
_low1_mask = tuple(reversed(_high0_mask))

def make_property(bytefield_name, offset, bits):
	if offset < 0 or bits < 0:
		raise ValueError('invalid offset or bit count')
	
	max_val = (1 << bits) - 1
	
	start = offset // 8
	start_bits = 8 - (offset % 8)
	
	# note: end points 1 byte past the end if end_bits == 0
	end_offset = offset + bits
	end = end_offset // 8
	end_bits = (end_offset % 8)
	shift = 8 - end_bits
	
	if start == end:
		mask = _high1_mask[bits] >> (offset % 8)
	else:
		start_mask = _high0_mask[offset % 8]
		end_mask = _high1_mask[end_bits]
		end_shmask = _high1_mask[end_bits] >> shift
	
	def get_simple(self):
		return (getattr(self, bytefield_name)[start] & mask) >> shift
	
	def get_multibyte(self):
		# this function assumes start != end (use get_simple otherwise)
		data = getattr(self, bytefield_name)
		
		val = 0
		pos = start
		if start_bits:
			val = data[start] & start_mask
			pos += 1
		
		while pos < end:
			val = (val << 8) | data[pos]
			pos += 1
		
		if end_bits:
			val = (val << end_bits) | (data[end] >> shift)
		
		return val
	
	def set_whole(self, val):
		getattr(self, bytefield_name)[start] = (val & 0xff)
	
	def set_masked(self, val):
		data = getattr(self, bytefield_name)
		data[start] = (data[start] & ~mask) | ((val << shift) & mask)
	
	def set_multibyte(self, val):
		# this function assumes start != end
		data = getattr(self, bytefield_name)
		
		pos = end
		if end_bits:
			data[end] = ( (data[end] & ~end_mask)
					| ((val & end_shmask) << shift) )
			val >>= end_bits
		
		pos -= 1
		while pos > start:
			data[pos] = (val & 0xff)
			val >>= 8
			pos -= 1
		
		if start_bits:
			data[start] = ( (data[start] & ~start_mask)
					| (val & start_mask) )
		
		# done
	
	
	if start == end:
		getfn = get_simple
		setfn = set_whole if (bits == 8) else set_masked
	else:
		getfn = get_multibyte
		setfn = set_multibyte
	
	return property(getfn, setfn)


if __name__=='__main__':
	from bitfields import *;import array
	class Q(object):
		a=make_property('raw', 0, 3)
		b=make_property('raw', 3, 11)
		c=make_property('raw', 3+11, 32)
	
	q=Q()
	q.raw=array.array('B')
	q.raw.fromstring('\xaf\x83\x99\x99\x99\x99')
	assert q.a==5
	q.a=7
	assert q.a==7
	assert q.c == (0x399999999 >> 2)
	q.c = 0x23587615
	assert q.c == 0x23587615
	q.b = (1<<11)-1
	assert q.b == (1<<11)-1
	q.b = 123
	assert q.b == 123
