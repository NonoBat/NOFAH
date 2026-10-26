{{ config(
    severity='warn',
    warn_if='>0',
    error_if='>10'
) }}

-- On sélectionne les stations qui n'ont pas un nombre de vélos disponibles cohérent avec leur capacité
select
    s.station_id,
    s.reported_at,
    s.bikes_available,
    i.capacity
from {{ ref('stg_station_status') }} s
join {{ ref('stg_station_information') }} i
    using (station_id)
where s.bikes_available < 0
   or s.bikes_available > i.capacity
