import asyncio
from loguru import logger
import random
import primp
from src.model.help.captcha import Capsolver, Solvium
from src.utils.config import Config
from eth_account import Account
import hashlib
from pynocaptcha import CloudFlareCracker, TlsV1Cracker
from curl_cffi.requests import AsyncSession
from src.model.monad_xyz.tls_op import make_wanda_request
from src.utils.tls_client import TLSClient
import json
import platform


async def faucet(
    session: primp.AsyncClient,
    account_index: int,
    config: Config,
    wallet: Account,
    proxy: str,
) -> bool:
    for retry in range(config.SETTINGS.ATTEMPTS):
        try:
            logger.info(
                f"[{account_index}] | Starting faucet for account {wallet.address}..."
            )
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
            href = "https://testnet.monad.xyz/"

            if config.FAUCET.USE_SOLVIUM_FOR_CLOUDFLARE:
                logger.info(
                    f"[{account_index}] | Solving Cloudflare challenge with Solvium..."
                )
                solvium = Solvium(
                    api_key=config.FAUCET.SOLVIUM_API_KEY,
                    session=session,
                    proxy=proxy,
                )

                result = await solvium.solve_captcha(
                    sitekey="0x4AAAAAAA-3X4Nd7hf3mNGx",
                    pageurl="https://testnet.monad.xyz/",
                )
                cf_result = result

            elif config.FAUCET.USE_CAPSOLVER_FOR_CLOUDFLARE:
                logger.info(
                    f"[{account_index}] | Solving Cloudflare challenge with Capsolver..."
                )
                capsolver = Capsolver(
                    api_key=config.FAUCET.CAPSOLVER_API_KEY,
                    proxy=proxy,
                    session=session,
                )
                cf_result = await capsolver.solve_turnstile(
                    "0x4AAAAAAA-3X4Nd7hf3mNGx",
                    "https://testnet.monad.xyz/",
                )

            else:
                # Solve Cloudflare challenge - matching working example configuration
                logger.info(
                    f"[{account_index}] | Solving Cloudflare challenge with Nocaptcha..."
                )
                cracker = CloudFlareCracker(
                    internal_host=True,
                    user_token=config.FAUCET.NOCAPTCHA_API_KEY,
                    href=href,
                    sitekey="0x4AAAAAAA-3X4Nd7hf3mNGx",
                    proxy=proxy,
                    debug=False,
                    show_ad=False,
                    timeout=60,
                )
                cf_result = cracker.crack()
                cf_result = cf_result["token"]

            if not cf_result:
                raise Exception("Failed to solve Cloudflare challenge")

            logger.success(f"[{account_index}] | Cloudflare challenge solved")

            # Generate visitor ID the same way as working example
            visitor_id = hashlib.md5(str(random.random()).encode()).hexdigest()

            json_data = {
                "address": wallet.address,
                "visitorId": visitor_id,
                "cloudFlareResponseToken": cf_result,
            }

            # Заменяем TlsV1Cracker на асинхронный запрос
            logger.info(f"[{account_index}] | Sending claim request...")

            headers = {
                'accept': '*/*',
                'accept-language': 'en-GB,en-US;q=0.9,en;q=0.8,ru;q=0.7,zh-TW;q=0.6,zh;q=0.5',
                'content-type': 'application/json',
                'origin': 'https://testnet.monad.xyz',
                'priority': 'u=1, i',
                'referer': 'https://testnet.monad.xyz/',
                'sec-ch-ua': '"Google Chrome";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'cross-site',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
            }

            curl_session = AsyncSession(
                impersonate="chrome131",
                proxies={"http": f"http://{proxy}", "https": f"http://{proxy}"},
                verify=False,
            )

            claim_result = await curl_session.post(
                "https://faucet-claim.molandak.org/",
                headers=headers,
                json=json_data,
            )
            response_text = claim_result.text
            status_code = claim_result.status_code

            # # Проверка операционной системы
            # if platform.system().lower() != "windows":
            #     curl_session = AsyncSession(
            #         impersonate="chrome131",
            #         proxies={"http": f"http://{proxy}", "https": f"http://{proxy}"},
            #         verify=False,
            #     )

            #     claim_result = await curl_session.post(
            #         "https://faucet-claim-2.monadinfra.com/",
            #         headers=headers,
            #         json=json_data,
            #     )
            #     response_text = claim_result.text
            #     status_code = claim_result.status_code

            # else:
            #     logger.info(f"[{account_index}] | Initializing TLS client...")
            #     tls_client = TLSClient()
            #     # response_text = claim_result.text

            #     # Выполняем запрос через TLS клиент
            #     logger.info(
            #         f"[{account_index}] | Sending claim request via TLS client..."
            #     )

            #     # Преобразуем прокси в формат http://user:pass@ip:port
            #     proxy_parts = proxy.split("@")
            #     if len(proxy_parts) == 2:
            #         proxy_url = f"http://{proxy}"
            #     else:
            #         proxy_url = f"http://{proxy}"

            #     response = tls_client.make_request(
            #         url="https://faucet-claim-2.monadinfra.com/",
            #         method="POST",
            #         headers=headers,
            #         data=json_data,
            #         proxy=proxy_url,
            #         tls_client_identifier="chrome_133",
            #         follow_redirects=False,
            #         timeout_seconds=30,
            #     )

            #     # Получаем текст ответа
            #     response_text = response.get("body", "")
                # status_code = response.get("status", 0)

            logger.info(
                f"[{account_index}] | Received response with status code: {status_code}"
            )

            if "Faucet is currently closed" in response_text:
                logger.error(f"[{account_index}] | Faucet is currently closed")
                return False

            if "used Cloudflare to restrict access" in response_text:
                logger.error(f"[{account_index}] | Cloudflare solved wrong...")
                continue

            if not response_text:
                raise Exception("Failed to send claim request")

            if '"Success"' in response_text:
                logger.success(
                    f"[{account_index}] | Successfully got tokens from faucet"
                )
                return True

            if "Claimed already" in response_text or "You have already claimed the faucet" in response_text:
                logger.success(
                    f"[{account_index}] | Already claimed tokens from faucet"
                )
                return True

            if '"message":"Success"' in response_text:
                logger.success(
                    f"[{account_index}] | Successfully got tokens from faucet"
                )
                return True
            else:
                if "FUNCTION_INVOCATION_TIMEOUT" in response_text:
                    logger.error(
                        f"[{account_index}] | Failed to get tokens from faucet: server is not responding, wait..."
                    )
                elif "Vercel Security Checkpoint" in response_text:
                    logger.error(
                        f"[{account_index}] | Failed to solve Vercel challenge, trying again..."
                    )
                    continue
                elif "Server error on QuickNode API" in response_text:
                    logger.error(
                        f"[{account_index}] | FAUCET DOES NOT WORK, QUICKNODE IS DOWN"
                    )
                elif "Over Enterprise free quota" in response_text:
                    logger.error(
                        f"[{account_index}] | MONAD IS SHIT, FAUCET DOES NOT WORK, TRY LATER"
                    )
                    return False
                elif "invalid-keys" in response_text:
                    logger.error(
                        f"[{account_index}] | PLEASE UPDATE THE BOT USING GITHUB"
                    )
                    return False
                else:
                    logger.error(
                        f"[{account_index}] | Failed to get tokens from faucet: {response_text}"
                    )
                await asyncio.sleep(3)

        except Exception as e:
            random_pause = random.randint(
                config.SETTINGS.RANDOM_PAUSE_BETWEEN_ACTIONS[0],
                config.SETTINGS.RANDOM_PAUSE_BETWEEN_ACTIONS[1],
            )

            if "operation timed out" in str(e):
                logger.error(
                    f"[{account_index}] | Error faucet to monad.xyz ({retry + 1}/{config.SETTINGS.ATTEMPTS}): Connection timed out. Next faucet in {random_pause} seconds"
                )
            else:
                logger.error(
                    f"[{account_index}] | Error faucet to monad.xyz ({retry + 1}/{config.SETTINGS.ATTEMPTS}): {e}. Next faucet in {random_pause} seconds"
                )
            await asyncio.sleep(random_pause)
            continue
    return False
