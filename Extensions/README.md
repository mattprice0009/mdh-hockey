# Extension announcements

Preview an announcement without posting it. Omit `--group` to use one more than the group recorded in worksheet cell AB8:

```bash
python Extensions/main.py
```

An explicit group still overrides AB8:

```bash
python Extensions/main.py --group 39
```

Process the previous group free-agent claims on Fantrax before previewing:

```bash
python Extensions/main.py --group 39 --process
```

`--process` is independent from `--post`, so both may be used together. Processing is destructive: the command aborts if any previous-group player already has an executed `ADD`, `CLAIM`, or `CLAIM - FA` transaction, or if Fantrax rejects the commissioner action.

## Discord webhook setup

Create an incoming webhook for the target channel using [Discord's webhook setup](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks), then add its URL to the ignored `mdhhockey/config.cfg` file:

```ini
[discord]
webhook_url = https://discord.com/api/webhooks/WEBHOOK_ID/WEBHOOK_TOKEN
```

Then post the announcement:

```bash
python Extensions/main.py --group 39 --post
```

Without `--post`, the command only prints a preview. With `--post`, it sends the same announcement and waits for Discord to confirm that the message was created.

Treat the webhook URL as a secret and do not commit it. Webhook messages allow Discord mentions. Labels such as `@OTH` remain plain text, while valid Discord mention syntax such as `<@USER_ID>`, `<@&ROLE_ID>`, `@everyone`, and `@here` can notify their targets.
