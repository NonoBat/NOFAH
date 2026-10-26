select
    cast(s.station_id as integer)  as station_id,
    to_timestamp(s.last_reported)  as reported_at,
    to_timestamp(last_updated)     as feed_updated_at,
    s.num_bikes_available          as bikes_available,
    s.is_installed = 1             as is_installed
from (
    select last_updated, unnest(data.stations) as s
    from read_json('{{ var("bronze") }}/station_status/*/*.json')
)
qualify row_number() over (
    partition by s.station_id, s.last_reported
    order by last_updated) = 1
