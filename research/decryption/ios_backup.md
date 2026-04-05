# iOS KakaoTalk Backup Extraction

## Status: Not started

## Overview

KakaoTalk on iOS stores data within the app container, accessible through
iTunes/Finder encrypted backups or filesystem extraction on jailbroken devices.

## Backup Methods

### Method 1: iTunes/Finder Encrypted Backup

1. Create encrypted backup via Finder (macOS) or iTunes (Windows)
2. Use `iphone-backup-tools` or `iMazing` to extract app data
3. KakaoTalk data location in backup:
   ```
   AppDomainGroup-group.com.kakao.talk/
   ```

### Method 2: libimobiledevice

Open-source alternative for backup extraction:
```bash
idevicebackup2 backup --full ./backup_dir
```

### Method 3: Jailbroken Device

Direct filesystem access to:
```
/var/mobile/Containers/Data/Application/<UUID>/
```

## Database Files

- `KakaoTalk.sqlite` - Main chat database
- `KakaoTalkMedia.sqlite` - Media references

## Encryption

iOS KakaoTalk database may or may not use SQLCipher depending on version.
The iOS Keychain may store the encryption key.

## Requirements

1. Physical iOS device with KakaoTalk
2. Device backup password (for encrypted backups)
3. Tools: `idevicebackup2`, `iphone-backup-tools`, or commercial software

## References

- libimobiledevice project
- iOS backup forensics documentation
