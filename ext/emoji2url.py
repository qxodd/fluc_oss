unicode_emojis = [
    f'{ord(emoji[0]):X}'.lower() for emoji in
    [
        '💥',
        '😈',
        '🤡',
        '💩',
        '🖕',
        '💀',
        '🤣',
        '☠️',
        '👹',
        '😡',
        '😢',
        '👏',
        '😹',
        '🖤',
        '📢',
        '🤓',
        '☝',
        '😨',
        '😏',
        '🤔',
        '🪦',
        '🎉',
        '🔥',
        '⚡',
        '💣',
        '👾',
        '🧨',
        '🛠️',
        '🎯',
        '🌀',
        '🌪️'
    ]
]

urls = [      
    f'https://images.emojiterra.com/twitter/v14.0/128px/{code}.png'
    for code in unicode_emojis
]
with open('urls.txt', 'w') as file:
    file.write('\n'.join(urls))