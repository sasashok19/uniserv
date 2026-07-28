-- V3's seed data left 'PLACEHOLDER_BCRYPT_HASH' in password_hash for the three
-- documented demo accounts. api-gateway's DevPasswordSeeder replaces that
-- placeholder with a real bcrypt hash on startup, but only when
-- APP_ENV=development — so any environment running with APP_ENV=production
-- (e.g. this project's live Render deployment) never gets past the
-- placeholder, and login fails with a 500 (BcryptUtil/ModularCrypt can't
-- parse 'PLACEHOLDER_BCRYPT_HASH' as a crypt string).
--
-- Real bcrypt hashes for the documented demo passwords (Admin@123 / Lead@123
-- / Agent@123 — already public in README.md, not a real secret). The WHERE
-- guard makes this a no-op wherever DevPasswordSeeder already replaced the
-- placeholder with its own hash.
UPDATE agents SET password_hash = '$2a$10$MBfjQIeM8.SsbJ.xMKbPTObGwK8jbgTgIBJ5vyLmj3qpGqeKBqLDm'
  WHERE email = 'admin@tneb.demo' AND password_hash = 'PLACEHOLDER_BCRYPT_HASH';
UPDATE agents SET password_hash = '$2a$10$znm8AJ9GhSBulUm5FfQU4.UWB.dlUHPiCKH6rvOS88Rz2Fw9OrxEK'
  WHERE email = 'lead@tneb.demo' AND password_hash = 'PLACEHOLDER_BCRYPT_HASH';
UPDATE agents SET password_hash = '$2a$10$3nCe.7spsoqjMu.yVY.1rehEuEiDOXQV06u4iifdNIvMYPMCybQfm'
  WHERE email = 'agent@tneb.demo' AND password_hash = 'PLACEHOLDER_BCRYPT_HASH';
