import asyncio
import time
import os
from exchanges import fetch_all_prices, fetch_spot_prices, get_max_entry
from spread import find_spreads, get_closed_spreads
from notifier import send_all_spreads, send_closed_alert, send_message
from bot_server import run_bot_server, set_current_spreads
from monitor import monitor_positions
from trader import init_trading_exchanges, get_all_balances
from database import (init_db, save_spread, get_top_spreads_by_history,
                      is_blacklisted, check_and_blacklist,
                      get_spread_stats, get_blacklist)
from verifier import verify_spread
from price_analyzer import (save_prices, check_convergence,
                             should_send_alert, get_best_coins_by_convergence)

sent_alerts = {}
scan_count  = 0

async def run_scanner():
    global scan_count

    init_db()
    print("\n🔑 Подключаем торговые аккаунты...")
    init_trading_exchanges()
    print("\n💵 Проверяем балансы...")
    get_all_balances()

    while True:
        try:
            scan_count += 1
            print("\n" + "=" * 50)
            print(f"🕐 {time.strftime('%H:%M:%S')} | Скан #{scan_count}")
            print("=" * 50)

            now = time.time()

            # Загрузка цен
            all_prices  = fetch_all_prices()
            spot_prices = fetch_spot_prices()
            total       = sum(len(v) for v in all_prices.values())
            print(f"✅ Загружено пар: {total}")

            # Сохраняем цены и конвергенции
            save_prices(all_prices)
            convergences = check_convergence(all_prices)
            if convergences:
                print(f"  🔄 Конвергенций: {len(convergences)}")

            # Мониторим позиции
            await monitor_positions(all_prices)

            # Ищем спреды
            print("\n🔍 Ищем спреды от 3%...")
            spreads = find_spreads(
                all_prices,
                spot_prices=spot_prices,
                min_spread_pct=3.0
            )

            set_current_spreads(spreads)

            # Закрытые спреды
            current_keys = {s['key'] for s in spreads}
            for c in get_closed_spreads(current_keys):
                print(f"  🔕 Закрылся: {c['key']} был {c['pct']}%")
                await send_closed_alert(c)

            if not spreads:
                print("  📭 Спредов не найдено")
            else:
                print(f"  📊 Найдено: {len(spreads)}")

            new_spreads = []

            for s in spreads[:20]:
                key     = s['key']
                last    = sent_alerts.get(key, 0)
                coin    = s['coin']
                buy_ex  = s['buy_exchange']
                sell_ex = s['sell_exchange']

                if now - last < 600:
                    continue
                if s['net_profit'] <= 0:
                    print(f"  ⛔ {coin} убыточен ({s['net_profit']}%)")
                    continue

                # Чёрный список
                if is_blacklisted(coin, buy_ex, sell_ex):
                    print(f"  🚫 {coin} в чёрном списке")
                    continue

                if check_and_blacklist(coin, buy_ex, sell_ex):
                    continue

                # ━━━━━━━━━━━━━━━━━━━━━━━━
                # Главный фильтр — только спреды
                # которые хоть раз сходились
                # ━━━━━━━━━━━━━━━━━━━━━━━━
                ok, reason = should_send_alert(s)
                print(f"  {reason}")
                if not ok:
                    continue

                # Верификация монеты
                is_valid = await verify_spread(s)
                if not is_valid:
                    continue

                # История
                stats = get_spread_stats(coin, buy_ex, sell_ex)
                if stats:
                    s['history'] = stats

                save_spread(s)

                # Макс входы
                buy_symbol = sell_symbol = None
                for symbol in all_prices.get(buy_ex, {}).keys():
                    if symbol.startswith(coin + '/'):
                        buy_symbol = symbol
                        break
                for symbol in all_prices.get(sell_ex, {}).keys():
                    if symbol.startswith(coin + '/'):
                        sell_symbol = symbol
                        break

                s['max_buy']  = get_max_entry(
                    buy_ex, buy_symbol
                ) if buy_symbol else 0
                s['max_sell'] = get_max_entry(
                    sell_ex, sell_symbol
                ) if sell_symbol else 0

                new_spreads.append(s)
                sent_alerts[key] = now

            if new_spreads:
                print(f"\n  📤 Отправляем {len(new_spreads)} спредов")
                await send_all_spreads(new_spreads, all_prices)
            else:
                print("\n  ⏭ Нет новых проверенных спредов")

            # История каждые 10 сканов
            if scan_count % 10 == 0:
                top = get_top_spreads_by_history(5)
                if top:
                    print("\n📚 Топ надёжных спредов:")
                    for t in top:
                        print(
                            f"  ✅ {t['coin']} "
                            f"{t['buy_exchange']}→{t['sell_exchange']} "
                            f"сходился:{t['converge_count']}x "
                            f"avg:{t['avg_spread']}%"
                        )

            if len(sent_alerts) > 1000:
                sent_alerts.clear()

            print(f"\n⏳ Следующий скан через 30 сек...")

        except Exception as e:
            print(f"\n❌ Ошибка: {e}")
            print("🔄 Перезапуск через 10 сек...")
            await asyncio.sleep(10)
            continue

        await asyncio.sleep(30)


async def main():
    print("🚀 Бот запущен!")
    print("📋 Биржи: BingX + MEXC")
    print("📋 Фильтр: только спреды которые сходились")
    print("-" * 50)

    await asyncio.gather(
        run_scanner(),
        run_bot_server(),
    )


if __name__ == '__main__':
    asyncio.run(main())
