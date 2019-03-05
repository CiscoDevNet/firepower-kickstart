#!/bin/sh
################################################################################
# The normal fmc image has 240G+ of empty space. AWS charges by image storage
# size and we have dd all that for at least the reads even with cov=sparse.
# So here we resize the image so that the whole disk is only 40G. This reduces
# storage costs and makes dd much faster.
#
# Then we remove the hardcoded password from the resized image to pass the AWS
# security test suite.
#
# --
# Chris Kindt
################################################################################

pre_install() {
    sudo apt-get update 2>&1
    sudo apt-get install -y qemu parted gnu-fdisk kpartx gddrescue 2>&1
    touch /mnt/fixup_pre_done
}

do_install() {
    qemu-img convert -O raw /mnt/image.qcow2 /mnt/image.raw
    kpartx -a -v /mnt/image.raw > /mnt/image.map

    sleep 3
    VOLPATH=$(ls /dev/mapper/loop*7)
    echo VOLPATH=$VOLPATH
    dumpe2fs $VOLPATH > /mnt/dumpe2fs-pre
    e2fsck -f  -y $VOLPATH
    sleep 3
    resize2fs $VOLPATH 26G 2>&1 > /mnt/dumpe2fs-resize
    sleep 3
    e2fsck -f -y $VOLPATH
    dumpe2fs $VOLPATH > /mnt/dumpe2fs-post
    sleep 3
    kpartx -v -d /mnt/image.raw
    sync

    parted /mnt/image.raw -s unit b print
    sfdisk -d /mnt/image.raw > /mnt/layout
    cat /mnt/layout
    #ext4 for disks this size have 4k blocks
    #blocks*8 gives 512b sectors
    #pad numbers with 100MiB(204800s) just in case
    #no wasted space since we resize /Volume at firstboot anyway
    EXTSTART=$(grep raw3 /mnt/layout | sed 's/,/ /' | awk '{print $4}')
    VARSTART=$(grep raw7 /mnt/layout | sed 's/,/ /' | awk '{print $4}')
    NEWBLOCKS=$(grep "Block count:" /mnt/dumpe2fs-post  | awk '{print $3}')
    NEWSECTORS=$(expr $NEWBLOCKS \* 8)
    VAREND=$(expr $VARSTART + $NEWSECTORS + 204800)
    EXTEND=$(expr $VAREND + 204800)
    VARSIZE=$(expr $NEWSECTORS + 204800)
    EXTSIZE=$(expr $EXTEND - $EXTSTART + 204800)

    echo EXTSTART=$EXTSTART
    echo VARSTART=$VARSTART
    echo NEWBLOCKS=$NEWBLOCKS
    echo NEWSECTORS=$NEWSECTORS
    echo VARSIZE=$VARSIZE
    echo EXTSIZE=$EXTSIZE
    echo VAREND=$VAREND
    echo EXTEND=$EXTEND

    sleep 3
    echo "$VARSTART,$VARSIZE" | sfdisk -u S -N 7 /mnt/image.raw
    sleep 3
    echo "$EXTSTART,$EXTSIZE" | sfdisk -u S -N 3 /mnt/image.raw
    sleep 3
    sync
    parted /mnt/image.raw -s unit b print
    sfdisk -d /mnt/image.raw > /mnt/layout2
    cat /mnt/layout2
    sync

    qemu-img resize /mnt/image.raw 40G
    #dd if=/mnt/image.raw of=/dev/xvdc bs=1M 2>&1
    #this is 90% faster, but less tested, should work
    dd conv=sparse if=/mnt/image.raw of=/dev/xvdc bs=1M 2>&1
    touch /mnt/fixup_done

}

post_install() {

    mkdir /aaa 2>&1
    partprobe 2>&1

    sleep 5

    mount /dev/xvdc5 /aaa
    cat /aaa/etc/passwd /aaa/etc/shadow > /mnt/passwd-pre
    chroot /aaa passwd -dl admin
    chroot /aaa passwd -dl root
    cat /aaa/etc/passwd /aaa/etc/shadow > /mnt/passwd-post
    umount /aaa
    sync
    sleep 3

}

case "$1" in
'preinstall')
  pre_install
  ;;
'doinstall')
  do_install
  ;;
'postinstall')
  post_install
  ;;
*)
esac

