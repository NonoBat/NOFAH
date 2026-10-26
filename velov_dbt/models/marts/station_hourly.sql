-- valeur à l'heure h : dernier relevé dans ]h - 1 h, h]
with hourly as (
    select
        s.station_id,
        date_trunc('hour', s.reported_at - interval 1 microsecond) + interval 1 hour as hour_ts,
        i.capacity,
        s.bikes_available,
        s.reported_at
    from {{ ref('stg_station_status') }} s
    join {{ ref('stg_station_information') }} i using (station_id)
)
select
    station_id,
    hour_ts as timestamp,
    cast(capacity as integer) as capacity,
    cast(bikes_available as integer) as bikes_available
from hourly
qualify row_number() over (
    partition by station_id, hour_ts
    order by reported_at desc
) = 1
