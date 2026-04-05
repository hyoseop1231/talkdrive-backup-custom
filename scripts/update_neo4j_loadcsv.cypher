// LOAD CSV로 EXIF 메타데이터 업데이트
LOAD CSV WITH HEADERS FROM 'file:///photos_exif.csv' AS row
MATCH (p:synology_photo {id: toInteger(row.id)})
SET p.latitude = CASE WHEN row.latitude <> '' THEN toFloat(row.latitude) ELSE null END,
    p.longitude = CASE WHEN row.longitude <> '' THEN toFloat(row.longitude) ELSE null END,
    p.resolution_width = CASE WHEN row.resolution_width <> '' THEN toInteger(row.resolution_width) ELSE null END,
    p.resolution_height = CASE WHEN row.resolution_height <> '' THEN toInteger(row.resolution_height) ELSE null END,
    p.camera_model = CASE WHEN row.camera_model <> '' THEN row.camera_model ELSE null END,
    p.aperture = CASE WHEN row.aperture <> '' THEN row.aperture ELSE null END,
    p.exposure_time = CASE WHEN row.exposure_time <> '' THEN row.exposure_time ELSE null END,
    p.focal_length = CASE WHEN row.focal_length <> '' THEN row.focal_length ELSE null END,
    p.iso = CASE WHEN row.iso <> '' THEN row.iso ELSE null END,
    p.lens = CASE WHEN row.lens <> '' THEN row.lens ELSE null END,
    p.address_country = CASE WHEN row.address_country <> '' THEN row.address_country ELSE null END,
    p.address_city = CASE WHEN row.address_city <> '' THEN row.address_city ELSE null END,
    p.address_route = CASE WHEN row.address_route <> '' THEN row.address_route ELSE null END,
    p.exif_updated = datetime()
RETURN count(p) AS updated_count;
