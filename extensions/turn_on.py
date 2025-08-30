import json
import os
import subprocess

import discord
from discord import app_commands
from discord.ext import commands, tasks
from netaddr import EUI, AddrFormatError, IPAddress
from wakeonlan import send_magic_packet

import constants

json_file = 'data.json'


def load_json():
    if not os.path.exists(json_file):
        # Create default structure if file doesn't exist
        default_data = {
            "mac_address": "",
            "ip_address": "",
            "password": "",
            "user_ids": [],
            "text_channel_id": None,
            "message_id": None
        }
        save_json(default_data)
        return default_data
    
    with open(json_file, 'r') as f:
        return json.load(f)


def save_json(data):
    with open(json_file, 'w') as f:
        json.dump(data, f, indent=4)


class TurnOnInitializeModal(discord.ui.Modal, title="Initialize PC"):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    mac_address = discord.ui.TextInput(label='MAC Address', placeholder='00:00:00:00:00:00', required=True)
    ip_address = discord.ui.TextInput(label='IP Address', placeholder='192.168.0.0', required=True)
    password = discord.ui.TextInput(label='Password (6 digits)', placeholder='Password', required=True, min_length=6, max_length=6)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # Check if MAC Address is valid
        try:
            EUI(self.mac_address.value)
        except AddrFormatError as afe:
            return await interaction.followup.send(content=f"Invalid MAC Address: {self.mac_address.value}\n```\n{afe}\n```", ephemeral=True)
        try:
            IPAddress(self.ip_address.value)
        except AddrFormatError as afe:
            return await interaction.followup.send(content=f"Invalid IP Address: {self.ip_address.value}\n```\n{afe}\n```", ephemeral=True)

        data = load_json()
        data['mac_address'] = self.mac_address.value
        data['ip_address'] = self.ip_address.value
        data['password'] = self.password.value
        data['user_ids'] = [interaction.user.id]
        save_json(data)

        await interaction.followup.send(content='PC has been initialized. Please run `create_button` command.', ephemeral=True)


class TurnOnModal(discord.ui.Modal, title="Authorize Password"):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    password = discord.ui.TextInput(label='Password', placeholder='Password', required=True, min_length=6, max_length=6)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        data = load_json()
        if self.password.value != data['password']:
            return await interaction.followup.send(content='[ERROR] Invalid password.', ephemeral=True)

        message = await interaction.followup.send(content='Password has been authorized.', ephemeral=True)

        try:
            # send_magic_packet(data['mac_address'], interface=data['ip_address'])
            result = subprocess.run(['wakeonlan', data['mac_address']])
            if result.returncode != 0:
                raise ValueError('failed to send WOL packet.')
        except Exception as e:
            return await message.edit(content=f'{message.content}\nFailed to send WOL packet.\n```\n{e}\n```')

        await message.edit(content=f'{message.content}\nWOL packet has been sent.')


class TurnOnButton(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label='Turn On PC', style=discord.ButtonStyle.green, custom_id='turn_on')
    async def _turn_on_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_json()
        if not data['mac_address'] or not data['ip_address'] or not data['password'] or not data['user_ids']:
            return await interaction.response.send_message('[ERROR] Please initialize PC first.', ephemeral=True)

        data = load_json()
        if not interaction.user.id in data['user_ids']:
            return await interaction.response.send_message('[ERROR] You do not have permission to turn on PC.', ephemeral=True)

        await interaction.response.send_modal(TurnOnModal(self.bot))


class TurnOnPC(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_view(TurnOnButton(self.bot))
        self.pc_status = None

    @commands.Cog.listener(name='on_ready')
    async def on_ready(self):
        self.change_status_message.start()

    @app_commands.command(name='init', description='Initialize')
    async def initialize(self, interaction: discord.Interaction):
        data = load_json()
        if data['user_ids'] and not interaction.user.id in data['user_ids']:
            return await interaction.response.send_message('[ERROR] You do not have permission to initialize PC.', ephemeral=True)

        await interaction.response.send_modal(TurnOnInitializeModal(self.bot))

    @app_commands.command(name='create_button', description='Create Button')
    async def create_button(self, interaction: discord.Interaction):
        data = load_json()
        if not data['mac_address'] or not data['ip_address'] or not data['password']:
            return await interaction.response.send_message('[ERROR] Please initialize PC first.', ephemeral=True)

        if not interaction.user.id in data['user_ids']:
            return await interaction.response.send_message('[ERROR] You do not have permission to create button.', ephemeral=True)

        if data['text_channel_id'] and data['message_id']:
            try:
                message = await self.bot.get_channel(data['text_channel_id']).fetch_message(data['message_id'])
                await message.delete()
            except discord.NotFound:
                pass

        message = await interaction.channel.send(view=TurnOnButton(self.bot))

        data['text_channel_id'] = interaction.channel.id
        data['message_id'] = message.id
        save_json(data)

        await interaction.response.send_message('Button has been created.', ephemeral=True)
        self.pc_status = None

    @app_commands.command(name='add_user', description='Add User')
    async def add_user(self, interaction: discord.Interaction, target: discord.User):
        data = load_json()
        if not data['mac_address'] or not data['ip_address'] or not data['password']:
            return await interaction.response.send_message('[ERROR] Please initialize PC first.', ephemeral=True)

        if not interaction.user.id in data['user_ids']:
            return await interaction.response.send_message('[ERROR] You do not have permission to add user.', ephemeral=True)

        if target.id in data['user_ids']:
            return await interaction.response.send_message('User has already been added.', ephemeral=True)

        data['user_ids'].append(target.id)
        save_json(data)

        await interaction.response.send_message('User has been added.', ephemeral=True)

    @app_commands.command(name='remove_user', description='Remove User')
    async def remove_user(self, interaction: discord.Interaction, target: discord.User):
        data = load_json()
        if not data['mac_address'] or not data['ip_address'] or not data['password']:
            return await interaction.response.send_message('[ERROR] Please initialize PC first.', ephemeral=True)

        if not interaction.user.id in data['user_ids']:
            return await interaction.response.send_message('[ERROR] You do not have permission to remove user.', ephemeral=True)

        if not target.id in data['user_ids']:
            return await interaction.response.send_message('User has not been added.', ephemeral=True)

        data['user_ids'].remove(target.id)
        save_json(data)

        await interaction.response.send_message('User has been removed.', ephemeral=True)

    @app_commands.command(name='info', description='Information')
    async def info(self, interaction: discord.Interaction):
        data = load_json()
        if not interaction.user.id in data['user_ids']:
            return await interaction.response.send_message('[ERROR] You do not have permission to view information.', ephemeral=True)

        users = [f"・{self.bot.get_user(user_id).mention}" for user_id in data['user_ids']]

        embed = discord.Embed(title='Information', color=0x00ff00)
        embed.add_field(name='MAC Address', value=data['mac_address'] if data['mac_address'] else 'Not set')
        embed.add_field(name='IP Address', value=data['ip_address'] if data['ip_address'] else 'Not set')
        embed.add_field(name='Password', value=data['password'] if data['password'] else 'Not set')
        embed.add_field(name='Users', value='\n'.join(users) if users else 'Not set')

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tasks.loop(seconds=30)
    async def change_status_message(self):
        print('Checking PC status...')
        data = load_json()
        if not data['mac_address'] or not data['ip_address'] or not data['password'] or not data['user_ids']:
            return

        if not data['text_channel_id'] or not data['message_id']:
            return

        result = subprocess.run(['ping', '-c 1', data['ip_address']], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if result.returncode == 0:
            new_pc_status = True
            embed = discord.Embed(title='🟢 PC is online', color=0x00ff00)
        else:
            new_pc_status = False
            embed = discord.Embed(title='🔴 PC is offline', color=0xff0000)

        print('PC status:', new_pc_status)

        if self.pc_status != new_pc_status:
            self.pc_status = new_pc_status
            try:
                message = await self.bot.get_channel(data['text_channel_id']).fetch_message(data['message_id'])
            except discord.NotFound:
                return

            await message.edit(embed=embed, view=TurnOnButton(self.bot))


async def setup(bot) -> None:
    await bot.add_cog(TurnOnPC(bot))
