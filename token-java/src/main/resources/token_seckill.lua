local packageId = ARGV[1]
local userId = ARGV[2]
local orderId = ARGV[3]
local stockKey = 'token:stock:' .. packageId
local orderKey = 'token:order:' .. packageId

local stock = tonumber(redis.call('get', stockKey))
if stock == nil or stock <= 0 then
    return 1
end
if redis.call('sismember', orderKey, userId) == 1 then
    return 2
end
redis.call('incrby', stockKey, -1)

--把 userId 加入到 Redis 的 Set 集合 orderKey 里。
redis.call('sadd', orderKey, userId)

--往 Redis Stream stream.token.orders 里追加一条消息。
redis.call('xadd', 'stream.token.orders', '*',
        'userId', userId, 'packageId', packageId, 'id', orderId)
return 0
