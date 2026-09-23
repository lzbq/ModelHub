local stockKey = KEYS[1]
local orderKey = KEYS[2]
local userId = ARGV[1]
--移出购买记录和恢复库存
if redis.call('srem', orderKey, userId) == 1 then
    redis.call('incrby', stockKey, 1)
end
return 0
