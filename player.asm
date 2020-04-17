; player.asm: Player movement code
; Copyright (C) 2020 Nathan Misner

; This program is free software; you can redistribute it and/or
; modify it under the terms of version 2 of the GNU General Public
; License as published by the Free Software Foundation.

; This program is distributed in the hope that it will be useful,
; but WITHOUT ANY WARRANTY; without even the implied warranty of
; MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
; GNU General Public License for more details.

; You should have received a copy of the GNU General Public License
; along with this program; if not, see
; <https://www.gnu.org/licenses/old-licenses/gpl-2.0.txt>
	.list
	.mlist
	.data
	.bank 1
	.code

TOP_SPEED .equ $400
ACCEL .equ $80
PLAYERSPR_X .equ 152 ;onscreen sprite position
PLAYERSPR_Y .equ 160
PLAYER_WIDTH .equ 16
PLAYER_HEIGHT .equ 32

player_init:
	;write player sprite to satb
	stw #PLAYERSPR_Y,satb ;y pos
	stw #PLAYERSPR_X,satb+2 ;x pos
	stw #($3000/32),satb+4 ;tile number
	stw	#%0_0_01_0_00_0_1_000_0000,satb+6 ;Attributes
	stw #PLAYERSPR_X,<player_x+1
	stw #PLAYERSPR_Y,<player_y+1
	
	rts

player_iterate:
;-----read input, set initial speed values-----
	bbr5 <joypad,.done_right
	cmpw #TOP_SPEED,<player_dx
	bpl .done_right
	addw #ACCEL,<player_dx
.done_right:
	bbr7 <joypad,.done_left
	cmpw #-TOP_SPEED,<player_dx
	bmi .done_left
	beq .done_left
	subw #ACCEL,<player_dx
.done_left:
	;deceleration only happens when not pressing left or right
	lda <joypad
	and #%10100000
	bne .done_decel
	cmpw #0,<player_dx
	;if player_dx is 0, don't decelerate
	beq .done_decel
	bpl .decel_right
	bmi .decel_left
.decel_right:
	subw #ACCEL,<player_dx
	;if value goes under zero, make it zero
	cmpw #0,<player_dx
	bpl .dont_zero_right
	stwz <player_dx
.dont_zero_right:
	bra .done_decel
.decel_left:
	addw #ACCEL,<player_dx
	; if value goes over zero, make it zero
	cmpw #0,<player_dx
	bmi .done_decel
	stwz <player_dx
.done_decel:
	;add dx to player_x
	lda <player_dx+1
	and #%10000000
	bne .negative_add
	;positive add
	addw <player_dx,<player_x
	lda player_x+2
	adc #$0
	sta player_x+2
	bra .done_add
.negative_add:
	addw <player_dx,<player_x
	lda player_x+2
	adc #$ff
	sta player_x+2
.done_add:
;-----collision detection-----
;check left foot
	stw <player_x+1,<_ax
	stw <player_y+1,<_bx
	addw #PLAYER_HEIGHT,<_bx
	jsr get_sensor
	stw <_dx,<pad
;check right foot
	stw <player_x+1,<_ax
	addw #PLAYER_WIDTH,<_ax
	stw <player_y+1,<_bx
	addw #PLAYER_HEIGHT,<_bx
	jsr get_sensor
	cmpw <pad,<_dx
	bmi .left_higher
	stw <_dx,<pad
.left_higher:
	;foot pos in ax
	stw <player_y+1,<_ax
	addw #PLAYER_HEIGHT,<_ax
	;place feet at bottom of block
	andw <_ax,#$fff0
	addw #16,<_ax
	;move up by highest sensor's height
	subw <pad,<_ax
	;translate from foot pos to sprite pos
	subw #PLAYER_HEIGHT,<_ax
	stw <_ax,<player_y+1

	
;-----done collision detection-----
	stw <player_x+1,<scroll_x
	subw #PLAYERSPR_X,<scroll_x
	stw <player_y+1,<scroll_y
	subw #PLAYERSPR_Y,<scroll_y
	rts
	
;returns number of pixels to move up/down in dx
;ax: foot x pos
;bx: foot y pos
get_sensor:
	stw <_ax,<_si
	stw <_bx,<_di
	jsr get_height
	sta <_dl
	stz <_dh
	;if height is 0, check below block
	beq .check_below
	cmp #16
	;if height is 16, check above block
	beq .check_above
	;otherwise end
	bra .end
.check_below:
	;add 16 to height (below tile)
	stw <_si,<_ax
	stw <_di,<_bx
	addw #16,<_bx
	jsr get_height
	sta <_dl
	;we have to remove 16px from the height
	subw #16,<_dx
	bra .end
.check_above:
	;subtract 16 from height (above tile)
	stw <_si,<_ax
	stw <_di,<_bx
	subw #16,<_bx
	jsr get_height
	sta <_dl
	;we have to add 16px to the height
	addw #16,<_dx
.end:
	rts


;returns height of current tile in al
;ax: x pos (pixels)
;bx: y pos (pixels)	
get_height:
;tile offset = ((y >> 4) << 6) + (x >> 4) << 1
;            = ((y & #$fff0) << 2) + (x >> 3) & #$fffe
	;pc engine adds 32 to sprite x positions and 64 to sprite y positions
	;so origin is 32 pixels left of screen and 64 above
	subw #32,<_ax
	subw #64,<_bx
	andw <_bx,#$fff0
	aslw <_bx
	aslw <_bx
	stw <_ax,<_cx
	lsrw <_cx
	lsrw <_cx
	lsrw <_cx
	andw <_cx,#$fffe
	addw <_cx,<_bx
	addw #map_load,<_bx
	;<_bx is the pointer to the tile
	lda [<_bx]
	tax
	;get height array index for the tile
	lda heights_load,x
	sta <_bl
	stz <_bh
	;each height array is 16 bytes, so shift left by 4 to get the offset
	aslw <_bx
	aslw <_bx
	aslw <_bx
	aslw <_bx
	addw #block_arrs,<_bx
	;get offset within the tile
	lda <_al
	and #$f
	tay
	lda [<_bx],y
	sta <_al
	rts
	
	