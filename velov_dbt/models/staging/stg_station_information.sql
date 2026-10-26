select
    cast(s.station_id as integer) as station_id,
    s.name                        as name,
    cast(s.capacity as integer)   as capacity
from (
    select unnest(data.stations) as s
    from read_json('{{ var("bronze") }}/station_information/*/*.json')
)
qualify row_number() over (
    partition by s.station_id
    order by s.name
) = 1
