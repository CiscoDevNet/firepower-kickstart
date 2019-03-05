from kick.azure.azure_lib import *

if __name__ == '__main__':
    start_time = time.time()

    # Provide the credentials for one of the methods chose for login to Azure

    az = AzureCLI(appid='APP_ID', dirid='DIR_ID', key='KEY')

    # Login to Azure using the credentials provided

    az.login_azure_cli()
    print("Logged into Azure CLI!")

    # Create a parameter file from a template

    az.create_parameter_file("/auto/rtp-ngfwv/arowlesl/ha_custom_image_parameters_template.json",
                             "/auto/rtp-ngfwv/arowlesl/testbed/testbed.yaml",
                             "/auto/rtp-ngfwv/arowlesl/parameters.json")
    print("Parameter File Created!")

    # Deploy from a template using a custom image

    az.deploy_from_template_custom_image(resource_group='arlrgtest',
                                         storage_name='arlautostorage',
                                         image_path='/auto/rtp-ngfwv/arowlesl/builds/asav101-2-1-14.vhd',
                                         template_file='/auto/rtp-ngfwv/arowlesl/mainTemplate-custom-image.json',
                                         parameter_file='/auto/rtp-ngfwv/arowlesl/parameters.json')
    print("Template deployed!")

    # Delete the resource group

    az.delete_rg("arlrgtest")
    print("Resource Group deleted!")

    # Delete the linux VM

    # az.delete_linux("arltestlinux", "arlrgtest")
    print("Linux VM deleted!")

    # Disconnect from Azure

    az.disconnect_azure()
    print('Disconnected from Azure')

    # Print runtime

    print("--- Runtime: %s seconds ---" % (time.time() - start_time))
