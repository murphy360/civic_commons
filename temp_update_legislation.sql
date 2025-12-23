UPDATE documents 
SET legislation_number = SUBSTRING(title FROM '^\d+-\d{2,4}')
WHERE document_type IN ('ordinance', 'resolution') 
AND legislation_number IS NULL 
AND title ~ '^\d+-\d{2,4}';
